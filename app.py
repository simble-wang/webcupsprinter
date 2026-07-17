"""
NAS 远程打印 Web 服务
通过网页上传文件，调用 CUPS 的 lp 命令完成打印。
"""

import os
import uuid
import time
import subprocess
import threading
import fitz  # PyMuPDF
from flask import Flask, render_template, request, jsonify, Response
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB，够打印用了

# ── 配置（全部走环境变量，docker-compose 里改） ──
UPLOAD_DIR = os.environ.get('UPLOAD_DIR', '/tmp/print_uploads')
PRINTER_NAME = os.environ.get('PRINTER_NAME', 'YourPrinterName')
CUPS_SERVER = os.environ.get('CUPS_SERVER', 'localhost:631')
CLEANUP_INTERVAL = 600   # 每 10 分钟扫一次
FILE_MAX_AGE = 3600      # 文件活 1 小时就删，别占地方

# 支持的文件格式：PDF、图片、纯文本、PostScript
ALLOWED_EXTENSIONS = {
    'pdf', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'tif',
    'txt', 'ps', 'eps', 'webp'
}

# NAS 本地文件目录（容器内的挂载路径）
LOCAL_FILES_DIR = os.environ.get('LOCAL_FILES_DIR', '/nas_files')

os.makedirs(UPLOAD_DIR, exist_ok=True)


def allowed_file(filename):
    """检查文件后缀是否在白名单里"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def cleanup_old_files():
    """后台线程：定期清理过期的上传文件，防止硬盘被撑爆"""
    while True:
        time.sleep(CLEANUP_INTERVAL)
        now = time.time()
        try:
            for f in os.listdir(UPLOAD_DIR):
                fp = os.path.join(UPLOAD_DIR, f)
                if os.path.isfile(fp) and now - os.path.getmtime(fp) > FILE_MAX_AGE:
                    os.remove(fp)
                    app.logger.info(f'已清理过期文件: {f}')
        except Exception as e:
            app.logger.error(f'清理文件失败: {e}')


# 启动清理线程（守护线程，主进程退了它也跟着走）
_cleanup = threading.Thread(target=cleanup_old_files, daemon=True)
_cleanup.start()


# ── 路由 ──

@app.route('/')
def index():
    return render_template('index.html', printer_name=PRINTER_NAME)


@app.route('/api/print', methods=['POST'])
def do_print():
    """核心接口：接收文件 + 打印参数 → 拼 lp 命令 → 执行"""

    if 'file' not in request.files:
        return jsonify({'success': False, 'error': '你倒是选个文件啊 😅'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': '文件名都没有，打印个寂寞？'}), 400

    if not allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[-1] if '.' in file.filename else '无'
        supported = '、'.join(sorted(ALLOWED_EXTENSIONS))
        return jsonify({
            'success': False,
            'error': f'不支持 .{ext} 格式。目前支持：{supported}'
        }), 400

    # 存文件：加 UUID 前缀防撞名
    safe_name = secure_filename(file.filename)
    if not safe_name:
        safe_name = f'upload.{file.filename.rsplit(".", 1)[-1] if "." in file.filename else "bin"}'
    unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
    filepath = os.path.join(UPLOAD_DIR, unique_name)
    file.save(filepath)

    # 拼 lp 命令
    cmd = ['lp', '-h', CUPS_SERVER, '-d', PRINTER_NAME]

    # 页码范围（如 1-3 或 1,3,5）
    page_range = request.form.get('page_range', '').strip()
    if page_range:
        cmd.extend(['-P', page_range])

    # 打印份数
    copies = request.form.get('copies', '1').strip()
    try:
        n = max(1, min(99, int(copies)))
        if n != 1:
            cmd.extend(['-n', str(n)])
    except ValueError:
        pass

    # 单面/双面
    duplex = request.form.get('duplex', 'one-sided')
    if duplex in ('two-sided-long-edge', 'two-sided-short-edge'):
        cmd.extend(['-o', f'sides={duplex}'])

    # 纸张大小
    paper_size = request.form.get('paper_size', 'A4')
    valid_sizes = ('A4', 'A3', 'A5', 'Letter', 'Legal', '4x6', '5x7')
    if paper_size in valid_sizes:
        cmd.extend(['-o', f'media={paper_size}'])

    # 自适应页面
    cmd.extend(['-o', 'fit-to-page'])

    # 加上文件路径
    cmd.append(filepath)

    app.logger.info(f'执行打印命令: {" ".join(cmd)}')

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': '打印任务已发送 🎉',
                'detail': result.stdout.strip(),
                'filename': file.filename
            })
        else:
            error_msg = result.stderr.strip() or result.stdout.strip() or '未知错误'
            app.logger.error(f'打印失败: {error_msg}')
            return jsonify({'success': False, 'error': f'打印失败: {error_msg}'}), 500
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'CUPS 没响应，可能卡住了'}), 500
    except Exception as e:
        app.logger.error(f'打印异常: {e}')
        return jsonify({'success': False, 'error': f'出错了: {str(e)}'}), 500


@app.route('/api/status')
def printer_status():
    """查询打印机状态"""
    try:
        result = subprocess.run(
            ['lpstat', '-h', CUPS_SERVER, '-p', PRINTER_NAME],
            capture_output=True, text=True, timeout=10
        )
        jobs_result = subprocess.run(
            ['lpstat', '-h', CUPS_SERVER, '-o', PRINTER_NAME],
            capture_output=True, text=True, timeout=10
        )

        status_text = result.stdout.strip()
        is_idle = 'idle' in status_text.lower()
        is_printing = 'printing' in status_text.lower()

        if is_idle:
            state = 'idle'
            state_text = '空闲待命 ✅'
        elif is_printing:
            state = 'printing'
            state_text = '正在打印... 🖨️'
        elif result.returncode != 0:
            state = 'error'
            state_text = '连接失败 ❌'
        else:
            state = 'unknown'
            state_text = status_text or '状态未知'

        return jsonify({
            'success': True,
            'state': state,
            'state_text': state_text,
            'raw': status_text,
            'jobs': jobs_result.stdout.strip(),
            'printer': PRINTER_NAME
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'state': 'error',
            'state_text': '无法连接 CUPS ❌',
            'error': str(e)
        }), 500


@app.route('/api/cancel', methods=['POST'])
def cancel_job():
    """取消打印任务"""
    data = request.get_json(silent=True) or {}
    job_id = str(data.get('job_id', '')).strip()
    if not job_id:
        return jsonify({'success': False, 'error': '缺少任务ID'}), 400

    try:
        subprocess.run(
            ['cancel', '-h', CUPS_SERVER, job_id],
            capture_output=True, text=True, timeout=10
        )
        return jsonify({'success': True, 'message': f'已取消任务 {job_id}'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ── NAS 本地文件浏览 ──

@app.route('/api/files')
def list_files():
    """浏览 NAS 本地目录，返回文件和文件夹列表"""
    rel_path = request.args.get('path', '')

    # 安全防护：防止 ../../../etc/passwd 这种路径穿越
    base = os.path.realpath(LOCAL_FILES_DIR)
    full_path = os.path.realpath(os.path.join(LOCAL_FILES_DIR, rel_path))
    if not full_path.startswith(base):
        return jsonify({'success': False, 'error': '别想偷溜出去 🚫'}), 403

    if not os.path.isdir(full_path):
        return jsonify({'success': False, 'error': '目录不存在'}), 404

    items = []
    try:
        for name in sorted(os.listdir(full_path), key=str.lower):
            if name.startswith('.'):
                continue  # 隐藏文件跳过
            item_path = os.path.join(full_path, name)
            if os.path.isdir(item_path):
                items.append({'name': name, 'type': 'dir'})
            elif os.path.isfile(item_path):
                ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
                size = os.path.getsize(item_path)
                items.append({
                    'name': name,
                    'type': 'file',
                    'size': size,
                    'ext': ext,
                    'printable': ext in ALLOWED_EXTENSIONS
                })
    except PermissionError:
        return jsonify({'success': False, 'error': '没有权限访问该目录'}), 403

    return jsonify({
        'success': True,
        'path': rel_path,
        'items': items
    })


@app.route('/api/print-local', methods=['POST'])
def print_local():
    """打印 NAS 本地文件，不需要上传"""
    data = request.get_json(silent=True) or {}
    file_path = data.get('path', '')

    if not file_path:
        return jsonify({'success': False, 'error': '没指定文件路径'}), 400

    # 安全防护
    base = os.path.realpath(LOCAL_FILES_DIR)
    full_path = os.path.realpath(os.path.join(LOCAL_FILES_DIR, file_path))
    if not full_path.startswith(base):
        return jsonify({'success': False, 'error': '路径不合法 🚫'}), 403

    if not os.path.isfile(full_path):
        return jsonify({'success': False, 'error': '文件不存在'}), 404

    # 检查格式
    ext = full_path.rsplit('.', 1)[-1].lower() if '.' in full_path else ''
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({'success': False, 'error': f'不支持 .{ext} 格式'}), 400

    # 拼 lp 命令
    cmd = ['lp', '-h', CUPS_SERVER, '-d', PRINTER_NAME]

    page_range = data.get('page_range', '').strip()
    if page_range:
        cmd.extend(['-P', page_range])

    copies = data.get('copies', 1)
    try:
        n = max(1, min(99, int(copies)))
        if n != 1:
            cmd.extend(['-n', str(n)])
    except (ValueError, TypeError):
        pass

    duplex = data.get('duplex', 'one-sided')
    if duplex in ('two-sided-long-edge', 'two-sided-short-edge'):
        cmd.extend(['-o', f'sides={duplex}'])

    paper_size = data.get('paper_size', 'A4')
    valid_sizes = ('A4', 'A3', 'A5', 'Letter', 'Legal', '4x6', '5x7')
    if paper_size in valid_sizes:
        cmd.extend(['-o', f'media={paper_size}'])

    cmd.extend(['-o', 'fit-to-page'])
    cmd.append(full_path)

    app.logger.info(f'打印本地文件: {" ".join(cmd)}')

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': '打印任务已发送 🎉',
                'detail': result.stdout.strip(),
                'filename': os.path.basename(full_path)
            })
        else:
            error_msg = result.stderr.strip() or result.stdout.strip() or '未知错误'
            return jsonify({'success': False, 'error': f'打印失败: {error_msg}'}), 500
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'CUPS 没响应'}), 500
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/download-cert')
def download_cert():
    """下载 SSL 证书文件，方便在 iPhone 上安装信任"""
    cert_path = os.path.join(os.path.dirname(__file__), '..', 'certs', 'cert.pem')
    # Docker 容器里证书挂载在 /etc/nginx/certs，但 Flask 容器需要单独挂载才能读
    # 这里用环境变量指定证书路径
    cert_path = os.environ.get('SSL_CERT_PATH', '/tmp/cert.pem')
    if not os.path.isfile(cert_path):
        return jsonify({'success': False, 'error': '证书文件不存在'}), 404
    with open(cert_path, 'rb') as f:
        data = f.read()
    return Response(data, mimetype='application/x-x509-ca-cert',
                    headers={'Content-Disposition': 'attachment; filename=nas-print-cert.pem'})


@app.errorhandler(413)
def too_large(e):
    return jsonify({'success': False, 'error': '文件太大了，最大 50MB'}), 413


# ── 缩略图预览 ──

# 图片格式 → MIME 映射
IMG_MIME = {
    'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg',
    'gif': 'image/gif', 'bmp': 'image/bmp', 'webp': 'image/webp',
}
# 支持多页预览的格式（PyMuPDF 能打开的）
MULTIPAGE_EXT = {'pdf', 'tiff', 'tif'}


@app.route('/api/page-count')
def page_count():
    """获取文件页数（PDF/TIFF 返回实际页数，图片返回1，其他返回0）"""
    path = request.args.get('path', '')

    base = os.path.realpath(LOCAL_FILES_DIR)
    full_path = os.path.realpath(os.path.join(LOCAL_FILES_DIR, path))
    if not full_path.startswith(base):
        return jsonify({'success': False, 'error': '路径不合法'}), 403

    if not os.path.isfile(full_path):
        return jsonify({'success': False, 'error': '文件不存在'}), 404

    ext = full_path.rsplit('.', 1)[-1].lower() if '.' in full_path else ''

    try:
        if ext in MULTIPAGE_EXT:
            doc = fitz.open(full_path)
            count = len(doc)
            doc.close()
            return jsonify({'success': True, 'pages': count})
        elif ext in IMG_MIME:
            return jsonify({'success': True, 'pages': 1})
        else:
            return jsonify({'success': True, 'pages': 0})
    except Exception as e:
        app.logger.error(f'获取页数失败: {e}')
        return jsonify({'success': False, 'error': str(e), 'pages': 0}), 500


@app.route('/api/thumbnail')
def thumbnail():
    """生成指定页的缩略图，返回 PNG 或原图。支持 width 参数调节分辨率"""
    path = request.args.get('path', '')
    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        page = 1
    try:
        width = max(80, min(1200, int(request.args.get('width', 150))))
    except ValueError:
        width = 150

    base = os.path.realpath(LOCAL_FILES_DIR)
    full_path = os.path.realpath(os.path.join(LOCAL_FILES_DIR, path))
    if not full_path.startswith(base):
        return jsonify({'success': False, 'error': '路径不合法'}), 403

    if not os.path.isfile(full_path):
        return jsonify({'success': False, 'error': '文件不存在'}), 404

    ext = full_path.rsplit('.', 1)[-1].lower() if '.' in full_path else ''

    try:
        if ext in MULTIPAGE_EXT:
            # PDF/TIFF：用 PyMuPDF 渲染指定页为 PNG
            doc = fitz.open(full_path)
            if page > len(doc):
                doc.close()
                return jsonify({'success': False, 'error': '页码超出范围'}), 400
            pg = doc[page - 1]
            # 缩略图宽度由 width 参数决定（默认 150，灯箱可用 600）
            zoom = width / pg.rect.width if pg.rect.width > 0 else 1.0
            mat = fitz.Matrix(zoom, zoom)
            pix = pg.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes('png')
            doc.close()
            return Response(img_bytes, mimetype='image/png')
        elif ext in IMG_MIME:
            # 普通图片：直接返回原文件，浏览器缩放
            with open(full_path, 'rb') as f:
                data = f.read()
            return Response(data, mimetype=IMG_MIME[ext])
        else:
            return jsonify({'success': False, 'error': '不支持预览此格式'}), 400
    except Exception as e:
        app.logger.error(f'缩略图生成失败: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
