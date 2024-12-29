from typing import Optional, Tuple, Generator
import os
import requests
import tempfile
import shutil
import gradio as gr

from facefusion import state_manager, wording
from facefusion.face_store import clear_reference_faces, clear_static_faces
from facefusion.filesystem import get_file_size, is_image, is_video
from facefusion.vision import get_video_frame, normalize_frame_color
from facefusion.uis.core import register_ui_component
from facefusion.uis.typing import ComponentOptions, File

FILE_SIZE_LIMIT = 512 * 1024 * 1024

# Gradio components
TARGET_FILE: Optional[gr.File] = None
TARGET_PATH_TEXTBOX: Optional[gr.Textbox] = None
DOWNLOAD_DIR_TEXTBOX: Optional[gr.Textbox] = None
TARGET_IMAGE: Optional[gr.Image] = None
TARGET_VIDEO: Optional[gr.Video] = None
PROGRESS_INFO: Optional[gr.Textbox] = None

def render() -> None:
    """
    Build the UI:
      1) A textbox for specifying a custom download folder.
      2) A textbox for an image/video path or direct URL.
      3) A File component to upload an image/video.
      4) Previews (image/video) + progress info.
    """
    global TARGET_FILE
    global TARGET_PATH_TEXTBOX
    global DOWNLOAD_DIR_TEXTBOX
    global TARGET_IMAGE
    global TARGET_VIDEO
    global PROGRESS_INFO

    # Fetch any previously chosen folder
    custom_temp_folder = state_manager.get_item('custom_temp_folder') or ""

    # Textbox for custom download path
    DOWNLOAD_DIR_TEXTBOX = gr.Textbox(
        label="Download Folder",
        value=custom_temp_folder,
        placeholder="e.g. /Users/username/Downloads (leave empty to use system temp)",
        max_lines=1
    )

    # Was there a previously set target_path?
    stored_target_path = state_manager.get_item('target_path')

    # Textbox for path/URL
    TARGET_PATH_TEXTBOX = gr.Textbox(
        label=wording.get('uis.target_file'),
        value=stored_target_path or "",
        placeholder="Enter a local path or direct link (image/video)",
        max_lines=1
    )

    # Determine if previously stored path is image or video
    is_target_image = is_image(stored_target_path)
    is_target_video = is_video(stored_target_path)
    TARGET_FILE = gr.File(
        label=wording.get('uis.target_file'),
        file_count='single',
        file_types=['image', 'video'],
        value=stored_target_path if (is_target_image or is_target_video) else None
    )

    # Prepare preview components
    target_image_options: ComponentOptions = {
        'show_label': False,
        'visible': False
    }
    target_video_options: ComponentOptions = {
        'show_label': False,
        'visible': False
    }

    if is_target_image:
        # If it's an image
        target_image_options['value'] = stored_target_path
        target_image_options['visible'] = True

    if is_target_video:
        # If it's a video
        if get_file_size(stored_target_path) > FILE_SIZE_LIMIT:
            preview_frame = normalize_frame_color(get_video_frame(stored_target_path))
            target_image_options['value'] = preview_frame
            target_image_options['visible'] = True
        else:
            target_video_options['value'] = stored_target_path
            target_video_options['visible'] = True

    TARGET_IMAGE = gr.Image(**target_image_options)
    TARGET_VIDEO = gr.Video(**target_video_options)

    PROGRESS_INFO = gr.Textbox(
        label="Download Progress",
        value="",
        interactive=False
    )

    # Register components
    register_ui_component('target_image', TARGET_IMAGE)
    register_ui_component('target_video', TARGET_VIDEO)

def listen() -> None:
    """
    We have three main interactions:
      1) DOWNLOAD_DIR_TEXTBOX change -> update_download_dir
      2) TARGET_PATH_TEXTBOX or TARGET_FILE change -> update
    """
    DOWNLOAD_DIR_TEXTBOX.change(
        fn=update_download_dir,
        inputs=DOWNLOAD_DIR_TEXTBOX,
        outputs=[]
    )

    TARGET_PATH_TEXTBOX.change(
        fn=update,
        inputs=[TARGET_PATH_TEXTBOX, TARGET_FILE],
        outputs=[TARGET_IMAGE, TARGET_VIDEO, PROGRESS_INFO]
    )

    TARGET_FILE.change(
        fn=update,
        inputs=[TARGET_PATH_TEXTBOX, TARGET_FILE],
        outputs=[TARGET_IMAGE, TARGET_VIDEO, PROGRESS_INFO]
    )

def update_download_dir(folder: str) -> None:
    """
    Save the user's chosen download directory (or clear if empty).
    """
    folder = folder.strip()
    if folder:
        state_manager.set_item('custom_temp_folder', folder)
    else:
        state_manager.clear_item('custom_temp_folder')

def update(
    textbox_value: str,
    file: File
) -> Generator[Tuple[gr.Image, gr.Video, str], None, None]:
    """
    Generator function that:
      - Takes the user's path or file
      - If it's a URL, we do chunk-based download
        to the user's chosen folder (or temp).
      - Then ensure final path is in an allowed directory
        (temp or CWD) before returning to Gradio.
      - Yields progress updates along the way.
    """
    clear_reference_faces()
    clear_static_faces()

    text_path = textbox_value.strip() if textbox_value else ""
    file_path = file.name if (file and hasattr(file, "name")) else ""

    # Prioritize file upload over text
    final_raw_path = file_path if file_path else text_path

    if not final_raw_path:
        # No input given
        state_manager.clear_item('target_path')
        yield (
            gr.Image(value=None, visible=False),
            gr.Video(value=None, visible=False),
            "No file or URL provided."
        )
        return

    local_path = None
    # If it's a URL => download it
    if final_raw_path.lower().startswith("http://") or final_raw_path.lower().startswith("https://"):
        local_path_generator = download_in_chunks(final_raw_path)
        for part in local_path_generator:
            if isinstance(part, tuple):
                # (downloaded, total, tmp_path)
                downloaded, total, tmp_file_path = part
                if total > 0:
                    pct = int(downloaded * 100 / total)
                    yield (
                        gr.Image(value=None, visible=False),
                        gr.Video(value=None, visible=False),
                        f"Downloading... %{pct}"
                    )
                else:
                    yield (
                        gr.Image(value=None, visible=False),
                        gr.Video(value=None, visible=False),
                        f"Downloaded bytes: {downloaded}"
                    )
            else:
                # final path
                local_path = part
                # Move the final file to an allowed directory so Gradio won't complain
                safe_path = ensure_in_allowed_dir(local_path)
                local_path = safe_path
                yield (
                    gr.Image(value=None, visible=False),
                    gr.Video(value=None, visible=False),
                    "Download complete!"
                )
    else:
        # Local path
        local_path = final_raw_path
        # Ensure it's in an allowed directory
        local_path = ensure_in_allowed_dir(local_path)

    if not local_path:
        state_manager.clear_item('target_path')
        yield (
            gr.Image(value=None, visible=False),
            gr.Video(value=None, visible=False),
            "Invalid or missing file."
        )
        return

    # Decide if image or video
    if is_image(local_path):
        state_manager.set_item('target_path', local_path)
        yield (
            gr.Image(value=local_path, visible=True),
            gr.Video(value=None, visible=False),
            "Image loaded!"
        )
        return

    if is_video(local_path):
        state_manager.set_item('target_path', local_path)
        if get_file_size(local_path) > FILE_SIZE_LIMIT:
            # Over the limit => show only first frame
            frame = normalize_frame_color(get_video_frame(local_path))
            yield (
                gr.Image(value=frame, visible=True),
                gr.Video(value=None, visible=False),
                "Video size too large. Showing first frame only."
            )
        else:
            yield (
                gr.Image(value=None, visible=False),
                gr.Video(value=local_path, visible=True),
                "Video loaded!"
            )
        return

    # Neither image nor video
    state_manager.clear_item('target_path')
    yield (
        gr.Image(value=None, visible=False),
        gr.Video(value=None, visible=False),
        "File is neither an image nor a video."
    )

def download_in_chunks(url: str):
    """
    Downloads from 'url' in chunks to the user-chosen folder or system temp.
    Yields (downloaded, total, tmp_path) after each chunk,
    then yields the final path string.
    """
    # Determine folder (user-chosen or system temp)
    custom_folder = state_manager.get_item('custom_temp_folder')
    if custom_folder:
        # If the user provided a folder, create it if needed
        os.makedirs(custom_folder, exist_ok=True)
        download_folder = custom_folder
    else:
        # Fallback to system temp
        download_folder = tempfile.gettempdir()
        os.makedirs(download_folder, exist_ok=True)

    _, ext = os.path.splitext(url)
    if not ext:
        ext = ".tmp"

    r = requests.get(url, stream=True)
    r.raise_for_status()

    total_size = r.headers.get("Content-Length")
    total_size = int(total_size) if total_size else 0

    downloaded = 0
    chunk_size = 1024 * 256

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir=download_folder) as tmp_file:
        tmp_path = tmp_file.name
        for chunk in r.iter_content(chunk_size=chunk_size):
            if chunk:
                tmp_file.write(chunk)
                downloaded += len(chunk)
                yield (downloaded, total_size, tmp_path)

    # Final yield => the fully downloaded path
    yield tmp_path

def ensure_in_allowed_dir(filepath: str) -> str:
    """
    If 'filepath' is not inside the current working directory or system temp,
    copy it to system temp. This avoids Gradio's InvalidPathError.
    """
    if not os.path.isfile(filepath):
        return ""

    if is_in_allowed_dir(filepath):
        return filepath  # Already safe

    temp_dir = tempfile.gettempdir()
    base_name = os.path.basename(filepath)
    new_path = os.path.join(temp_dir, base_name)
    shutil.copy2(filepath, new_path)
    return new_path

def is_in_allowed_dir(path: str) -> bool:
    """
    Return True if 'path' is within the current working directory or system temp.
    """
    real_p = os.path.realpath(path)
    real_cwd = os.path.realpath(os.getcwd())
    real_temp = os.path.realpath(tempfile.gettempdir())
    return (real_p.startswith(real_cwd) or real_p.startswith(real_temp))
