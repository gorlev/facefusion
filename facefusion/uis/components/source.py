import os
import requests
import tempfile
import shutil
from typing import List, Optional, Tuple

import gradio as gr

from facefusion import state_manager, wording
from facefusion.common_helper import get_first
from facefusion.filesystem import (
    filter_audio_paths,
    filter_image_paths,
    has_audio,
    has_image
)
from facefusion.uis.core import register_ui_component
from facefusion.uis.typing import File

# Global components
SOURCE_PATH_TEXTBOX: Optional[gr.Textbox] = None
SOURCE_FILE: Optional[gr.File] = None
SOURCE_AUDIO: Optional[gr.Audio] = None
SOURCE_IMAGE: Optional[gr.Image] = None

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".bmp")
AUDIO_EXTENSIONS = (".mp3", ".wav", ".ogg", ".flac")

def is_url(path: str) -> bool:
    """
    Return True if 'path' starts with http:// or https://
    """
    return path.lower().startswith("http://") or path.lower().startswith("https://")

def is_valid_local_file(path: str) -> bool:
    """
    Return True if 'path' exists on the local disk and is a file.
    """
    return os.path.isfile(path)

def download_file(url: str) -> str:
    """
    Download the file from the given URL and save it into
    the operating system's default temp directory.
    Then return the local path to the downloaded file.
    """
    temp_dir = tempfile.gettempdir()
    os.makedirs(temp_dir, exist_ok=True)

    # Extract the extension from the URL, if any
    _, ext = os.path.splitext(url)
    if not ext:
        ext = ".tmp"

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext, dir=temp_dir) as tmp_file:
        response = requests.get(url)
        response.raise_for_status()
        tmp_file.write(response.content)
        tmp_file_path = tmp_file.name

    return tmp_file_path

def process_path(path: str) -> Optional[str]:
    """
    If 'path' is a URL, download it to temp.
    If it's a local file path, check if it exists.
    If valid, return it; otherwise return None.
    """
    if is_url(path):
        return download_file(path)

    # Local file: verify it exists
    if is_valid_local_file(path):
        return path

    return None

def is_in_allowed_dirs(filepath: str) -> bool:
    """
    Return True if 'filepath' is located under either:
    - The current working directory
    - The system's temporary directory
    Otherwise, return False.
    """
    real_path = os.path.realpath(filepath)
    real_cwd = os.path.realpath(os.getcwd())
    real_temp = os.path.realpath(tempfile.gettempdir())

    # Check if the file is inside the current working directory or temp directory
    if real_path.startswith(real_cwd) or real_path.startswith(real_temp):
        return True
    return False

def ensure_in_temp(filepath: str) -> str:
    """
    If the file is not already in the working dir or temp dir,
    copy it to the temp directory and return the new path.
    """
    if is_in_allowed_dirs(filepath):
        # Already in an allowed directory
        return filepath

    # Otherwise, copy to system temp
    temp_dir = tempfile.gettempdir()
    os.makedirs(temp_dir, exist_ok=True)
    base_name = os.path.basename(filepath)
    new_path = os.path.join(temp_dir, base_name)

    shutil.copy2(filepath, new_path)
    return new_path

def render() -> None:
    """
    Build the UI components:
    1) A Textbox where the user can enter a path or direct link.
    2) A File component for uploading audio/image files.
    3) Audio and Image components to preview the loaded content.
    """
    global SOURCE_PATH_TEXTBOX
    global SOURCE_FILE
    global SOURCE_AUDIO
    global SOURCE_IMAGE

    # Retrieve stored paths
    stored_paths = state_manager.get_item('source_paths') or []
    stored_paths_str = ", ".join(stored_paths) if stored_paths else ""

    # Check existing audio/image in stored paths
    user_has_audio = has_audio(stored_paths)
    user_has_image = has_image(stored_paths)
    source_audio_path = get_first(filter_audio_paths(stored_paths)) if user_has_audio else None
    source_image_path = get_first(filter_image_paths(stored_paths)) if user_has_image else None

    # Textbox for manual path/link
    SOURCE_PATH_TEXTBOX = gr.Textbox(
        label=wording.get('uis.source_file'),
        value=stored_paths_str,
        placeholder="Example: C:/Users/.../sample.jpg, https://example.com/image.png",
        max_lines=1
    )

    # File upload component
    SOURCE_FILE = gr.File(
        label=wording.get('uis.source_file'),
        file_count='multiple',
        file_types=['audio', 'image'],
        value=stored_paths if user_has_audio or user_has_image else None
    )

    # Audio preview
    SOURCE_AUDIO = gr.Audio(
        value=source_audio_path if user_has_audio else None,
        visible=user_has_audio,
        show_label=False
    )

    # Image preview
    SOURCE_IMAGE = gr.Image(
        value=source_image_path if user_has_image else None,
        visible=user_has_image,
        show_label=False
    )

    # Register UI components
    register_ui_component('source_audio', SOURCE_AUDIO)
    register_ui_component('source_image', SOURCE_IMAGE)

def listen() -> None:
    """
    Listen for changes in both the Textbox and File components.
    Call 'update' with both inputs whenever either changes.
    """
    SOURCE_PATH_TEXTBOX.change(
        fn=update,
        inputs=[SOURCE_PATH_TEXTBOX, SOURCE_FILE],
        outputs=[SOURCE_AUDIO, SOURCE_IMAGE]
    )

    SOURCE_FILE.change(
        fn=update,
        inputs=[SOURCE_PATH_TEXTBOX, SOURCE_FILE],
        outputs=[SOURCE_AUDIO, SOURCE_IMAGE]
    )

def update(text_str: str, files: List[File]) -> Tuple[gr.Audio, gr.Image]:
    """
    1) Parse the Textbox input (comma-separated).
    2) Check the File component for uploaded files.
    3) For each path:
       - If it's a URL, download it to temp.
       - If it's local, verify it exists.
    4) Ensure each valid path is in an allowed directory
       (working dir or temp). If not, copy it to temp.
    5) Determine whether we have audio or images, then display them.
    """
    # 1) Parse the Textbox input
    textbox_paths = [p.strip() for p in text_str.split(",") if p.strip()]

    # 2) From the File component, extract local file paths
    file_paths = []
    if files:
        for f in files:
            if f is not None and hasattr(f, "name") and f.name:
                file_paths.append(f.name)

    # Combine and remove duplicates
    all_raw_paths = list(set(textbox_paths + file_paths))

    # Process each path (download if URL, validate local file)
    processed_paths = []
    for p in all_raw_paths:
        local_p = process_path(p)
        if local_p:
            # Step 4) If outside working/temp dirs, copy to temp
            safe_path = ensure_in_temp(local_p)
            processed_paths.append(safe_path)

    # 5) Decide if we have audio or images
    if has_audio(processed_paths) or has_image(processed_paths):
        source_audio_path = get_first(filter_audio_paths(processed_paths))
        source_image_path = get_first(filter_image_paths(processed_paths))

        # Update state
        state_manager.set_item('source_paths', processed_paths)

        return (
            gr.Audio(value=source_audio_path, visible=(source_audio_path is not None)),
            gr.Image(value=source_image_path, visible=(source_image_path is not None))
        )
    else:
        # No valid audio/image
        state_manager.clear_item('source_paths')
        return (
            gr.Audio(value=None, visible=False),
            gr.Image(value=None, visible=False)
        )
