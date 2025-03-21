


def infer_content_type(path:str) -> str: 
    if path.endswith(".html"): return "text/html"
    if path.endswith(".htm"): return "text/html"    
    if path.endswith(".css"): return "text/css"
    if path.endswith(".js"): return "application/javascript"
    if path.endswith(".png"): return "image/png"
    if path.endswith(".jpg"): return "image/jpeg"
    if path.endswith(".jpeg"): return "image/jpeg"
    if path.endswith(".svg"): return "image/svg+xml"
    if path.endswith(".ico"): return "image/x-icon"
    if path.endswith(".json"): return "application/json"
    if path.endswith(".woff"): return "font/woff"
    if path.endswith(".woff2"): return "font/woff2"
    if path.endswith(".ttf"): return "font/ttf"
    if path.endswith(".otf"): return "font/otf"
    if path.endswith(".eot"): return "font/eot"
    if path.endswith(".pdf"): return "application/pdf"
    if path.endswith(".doc"): return "application/msword"
    if path.endswith(".docx"): return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if path.endswith(".xls"): return "application/vnd.ms-excel"
    if path.endswith(".xlsx"): return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if path.endswith(".ppt"): return "application/vnd.ms-powerpoint"
    if path.endswith(".pptx"): return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if path.endswith(".zip"): return "application/zip"
    if path.endswith(".tar"): return "application/x-tar"
    if path.endswith(".gz"): return "application/gzip"
    if path.endswith(".bz2"): return "application/x-bzip2"
    if path.endswith(".7z"): return "application/x-7z-compressed"
    if path.endswith(".rar"): return "application/vnd.rar"
    if path.endswith(".mp4"): return "video/mp4"
    if path.endswith(".webm"): return "video/webm"
    if path.endswith(".ogg"): return "video/ogg"
    if path.endswith(".mp3"): return "audio/mpeg"
    if path.endswith(".wav"): return "audio/wav"
    if path.endswith(".flac"): return "audio/flac"
    if path.endswith(".aac"): return "audio/aac"
    if path.endswith(".opus"): return "audio/opus"
    if path.endswith(".avi"): return "video/x-msvideo"
    if path.endswith(".wmv"): return "video/x-ms-wmv"
    if path.endswith(".mov"): return "video/quicktime"
    if path.endswith(".mkv"): return "video/x-matroska"
    if path.endswith(".webp"): return "image/webp"
    if path.endswith(".bmp"): return "image/bmp"
    if path.endswith(".tiff"): return "image/tiff"
    if path.endswith(".gif"): return "image/gif"
    if path.endswith(".webm"): return "video/webm"
    if path.endswith(".webp"): return "image/webp"
    if path.endswith(".bmp"): return "image/bmp"
    if path.endswith(".tiff"): return "image/tiff"
    if path.endswith(".gif"): return "image/gif"
    return "application/octet-stream"
