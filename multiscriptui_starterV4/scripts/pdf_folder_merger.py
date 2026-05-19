import os
import shutil
from pathlib import Path

import pandas as pd
from PyPDF2 import PdfMerger, PdfReader
from PIL import Image
from fpdf import FPDF

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader

from core.io_utils import ensure_dir
from core.logging_utils import push_log


DESCRIPTION = (
    "Create one merged PDF for each child folder under a local root path. "
    "Recursively supports PDFs, images, and Excel files inside nested subfolders."
)

BADGES = ["Per-folder output", "Recursive folders", "Offline", "Mixed files"]

ASSISTANT_HINT = (
    "Give the local root folder path. Each child folder becomes one merged PDF, "
    "including files inside all nested subfolders."
)

SUPPORTS_LOCAL_PATHS = True

PARAMS = [
    {"name": "root_folder", "type": "text", "label": "Local root folder path"},
]


def natural_sort_key(path):
    return str(path).lower()


def safe_text(value):
    if pd.isna(value):
        return ""
    return str(value).encode("latin-1", "replace").decode("latin-1")


def make_safe_filename_from_path(path):
    """
    Creates a safe temporary filename from a full file path.

    This avoids name clashes when two nested folders contain files
    with the same name.
    """
    raw_name = "_".join(path.parts[-6:])

    safe_name = "".join(
        c if c.isalnum() or c in ("-", "_", ".") else "_"
        for c in raw_name
    )

    return safe_name


def is_inside_temp_dir(path):
    """
    Prevents the script from re-processing temporary conversion files.
    """
    return "_temp_pdf_conversion" in path.parts


def collect_supported_files_recursively(folder, log_queue=None):
    """
    Recursively collects supported files from a folder and all nested subfolders.

    If this folder is being processed:

        Root/
          Client A/
            file1.pdf
            scans/
              scan1.jpg
              scan2.png
            accounts/
              2024/
                workbook.xlsx

    Then all files under Client A are included in Client A.pdf.
    """

    supported_image_types = {
        ".jpg",
        ".jpeg",
        ".png",
        ".bmp",
        ".tiff",
        ".tif",
        ".webp",
    }

    supported_excel_types = {
        ".xls",
        ".xlsx",
    }

    pdf_files = []
    image_files = []
    excel_files = []

    for file_path in sorted(folder.rglob("*"), key=natural_sort_key):
        if not file_path.is_file():
            continue

        if is_inside_temp_dir(file_path):
            continue

        suffix = file_path.suffix.lower()

        if suffix == ".pdf":
            pdf_files.append(file_path)
        elif suffix in supported_image_types:
            image_files.append(file_path)
        elif suffix in supported_excel_types:
            excel_files.append(file_path)

    if log_queue is not None:
        push_log(
            log_queue,
            "INFO",
            (
                f"Found recursively in {folder}: "
                f"{len(pdf_files)} PDFs, "
                f"{len(image_files)} images, "
                f"{len(excel_files)} Excel files"
            ),
        )

    return pdf_files, image_files, excel_files


def get_image_dimensions_without_resizing(image_path):
    """
    Reads image dimensions only.

    This does not resize, resample, rotate, or modify the source image pixels.
    """
    with Image.open(str(image_path)) as image:
        width_px, height_px = image.size

    return width_px, height_px


def convert_images_to_pdf(image_files, temp_dir, log_queue):
    """
    Converts image files into A4-sized PDF pages without resizing image pixels.

    Important:
    - This does NOT call image.resize().
    - This does NOT rewrite the source image.
    - The image is drawn onto an A4 PDF page.
    - The image's display size is scaled to fit A4.
    - The image pixels themselves are not changed by this function.

    In PDF terms, the image is embedded and displayed within a rectangle.
    The rectangle size changes, not the original image pixel data.
    """

    pdf_files = []
    skipped = []

    page_width, page_height = A4

    # 36 points = 0.5 inch margin.
    margin = 36

    printable_width = page_width - (2 * margin)
    printable_height = page_height - (2 * margin)

    for img_path in image_files:
        try:
            img_width_px, img_height_px = get_image_dimensions_without_resizing(img_path)

            if img_width_px <= 0 or img_height_px <= 0:
                raise ValueError("Image has invalid dimensions.")

            # Calculate display size only.
            # This does not resize the image pixels.
            scale = min(
                printable_width / img_width_px,
                printable_height / img_height_px,
            )

            display_width = img_width_px * scale
            display_height = img_height_px * scale

            x = (page_width - display_width) / 2
            y = (page_height - display_height) / 2

            safe_name = make_safe_filename_from_path(img_path)
            pdf_path = temp_dir / f"{safe_name}_image_converted.pdf"

            c = canvas.Canvas(str(pdf_path), pagesize=A4)

            image_reader = ImageReader(str(img_path))

            c.drawImage(
                image_reader,
                x,
                y,
                width=display_width,
                height=display_height,
                preserveAspectRatio=True,
                mask="auto",
            )

            c.showPage()
            c.save()

            pdf_files.append(pdf_path)

        except Exception as e:
            skipped.append((str(img_path), str(e)))
            push_log(log_queue, "ERROR", f"Image conversion failed for {img_path}: {e}")

    return pdf_files, skipped


def convert_excel_to_pdf(excel_file, temp_dir, log_queue):
    """
    Converts Excel files to A4 PDF.

    This keeps your existing simple table layout, using A4 landscape pages.
    """

    output_pdfs = []
    skipped = []

    try:
        xls = pd.ExcelFile(str(excel_file))

        pdf = FPDF(orientation="L", unit="mm", format="A4")
        pdf.set_auto_page_break(auto=True, margin=10)

        for sheet_name in xls.sheet_names:
            try:
                df = pd.read_excel(
                    str(excel_file),
                    sheet_name=sheet_name,
                    dtype=str,
                ).fillna("")

                pdf.add_page()

                pdf.set_font("Arial", "B", 12)
                pdf.cell(
                    0,
                    10,
                    safe_text(f"File: {excel_file.name} | Sheet: {sheet_name}"),
                    ln=True,
                )

                pdf.set_font("Arial", size=8)
                pdf.cell(
                    0,
                    6,
                    safe_text(f"Source path: {excel_file}"),
                    ln=True,
                )

                pdf.ln(2)

                if df.empty:
                    pdf.cell(0, 8, "No data found in this sheet.", ln=True)
                    continue

                max_cols = min(len(df.columns), 8)
                display_df = df.iloc[:, :max_cols]

                # A4 landscape width is 297mm.
                # With 10mm margins on both sides, usable width is about 277mm.
                col_width = 277 / max_cols
                row_height = 6

                pdf.set_font("Arial", "B", 8)

                for col in display_df.columns:
                    pdf.cell(
                        col_width,
                        row_height,
                        safe_text(col)[:30],
                        border=1,
                    )

                pdf.ln(row_height)

                pdf.set_font("Arial", size=8)

                for _, row in display_df.iterrows():
                    for cell in row:
                        pdf.cell(
                            col_width,
                            row_height,
                            safe_text(cell)[:30],
                            border=1,
                        )
                    pdf.ln(row_height)

            except Exception as e:
                pdf.add_page()
                pdf.set_font("Arial", size=10)
                pdf.cell(
                    0,
                    10,
                    safe_text(f"Could not read sheet {sheet_name}: {e}"),
                    ln=True,
                )

        safe_name = make_safe_filename_from_path(excel_file)
        out_pdf = temp_dir / f"{safe_name}_excel_converted.pdf"

        pdf.output(str(out_pdf))
        output_pdfs.append(out_pdf)

    except Exception as e:
        skipped.append((str(excel_file), str(e)))
        push_log(log_queue, "ERROR", f"Excel conversion failed for {excel_file}: {e}")

    return output_pdfs, skipped


def merge_pdfs(pdf_files, output_pdf_path, log_queue):
    """
    Merges PDFs into one output file.

    Existing PDFs are appended as-is.
    They are not resized here.
    """

    merger = PdfMerger()
    added_count = 0
    skipped = []

    for pdf in pdf_files:
        try:
            reader = PdfReader(str(pdf))

            if reader.is_encrypted:
                decrypt_result = reader.decrypt("")
                if decrypt_result == 0:
                    skipped.append((str(pdf), "Password protected"))
                    continue

            _ = len(reader.pages)

            merger.append(reader)
            added_count += 1

        except Exception as e:
            skipped.append((str(pdf), str(e)))
            push_log(log_queue, "ERROR", f"Skipping unreadable PDF {pdf}: {e}")

    if added_count > 0:
        merger.write(str(output_pdf_path))
        push_log(log_queue, "INFO", f"Merged PDF created: {output_pdf_path}")

    merger.close()

    return skipped


def remove_temp_dir(temp_dir, log_queue):
    try:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
    except Exception as e:
        push_log(log_queue, "WARNING", f"Could not remove temp folder {temp_dir}: {e}")


def run(inputpath, outputpath, kwargs, log_queue=None):
    log_queue = log_queue or []
    ensure_dir(outputpath)

    root_folder = kwargs.get("root_folder", "").strip()

    if not root_folder or not os.path.isdir(root_folder):
        raise ValueError("Please provide a valid local root folder path.")

    root = Path(root_folder)
    output_root = Path(outputpath)

    all_outputs = []
    summary_rows = []

    for folder in sorted(root.iterdir(), key=natural_sort_key):
        if not folder.is_dir():
            continue

        push_log(log_queue, "INFO", f"Processing top-level folder: {folder}")

        skipped_all = []

        temp_dir = folder / "_temp_pdf_conversion"
        temp_dir.mkdir(exist_ok=True)

        try:
            source_pdf_files, image_files, excel_files = collect_supported_files_recursively(
                folder,
                log_queue,
            )

            converted_pdf_files = []

            img_pdfs, skipped_images = convert_images_to_pdf(
                image_files,
                temp_dir,
                log_queue,
            )

            converted_pdf_files.extend(img_pdfs)
            skipped_all.extend(skipped_images)

            for excel_file in excel_files:
                excel_pdfs, skipped_excels = convert_excel_to_pdf(
                    excel_file,
                    temp_dir,
                    log_queue,
                )

                converted_pdf_files.extend(excel_pdfs)
                skipped_all.extend(skipped_excels)

            pdf_files_to_merge = sorted(
                source_pdf_files + converted_pdf_files,
                key=natural_sort_key,
            )

            output_pdf_path = output_root / f"{folder.name}.pdf"

            if pdf_files_to_merge:
                skipped_merge = merge_pdfs(
                    pdf_files_to_merge,
                    output_pdf_path,
                    log_queue,
                )

                skipped_all.extend(skipped_merge)

                if output_pdf_path.is_file():
                    all_outputs.append(str(output_pdf_path))

            if skipped_all:
                log_file = output_root / f"{folder.name}_skipped_files.txt"

                with open(log_file, "w", encoding="utf-8") as f:
                    f.write(f"Skipped files log for folder: {folder.name}\n")
                    f.write(f"Source folder: {folder}\n\n")

                    for file_name, reason in skipped_all:
                        f.write(f"{file_name} --> {reason}\n")

                all_outputs.append(str(log_file))

            summary_rows.append({
                "top_level_folder": folder.name,
                "source_folder": str(folder),
                "source_pdf_count": len(source_pdf_files),
                "image_count": len(image_files),
                "excel_count": len(excel_files),
                "total_files_found": (
                    len(source_pdf_files)
                    + len(image_files)
                    + len(excel_files)
                ),
                "converted_image_pdf_count": len(img_pdfs),
                "converted_excel_pdf_count": len(converted_pdf_files) - len(img_pdfs),
                "total_pdf_inputs_after_conversion": len(pdf_files_to_merge),
                "skipped_count": len(skipped_all),
                "output_pdf": str(output_pdf_path) if output_pdf_path.is_file() else "",
            })

        finally:
            remove_temp_dir(temp_dir, log_queue)

    summary_df = pd.DataFrame(summary_rows)

    summary_path = output_root / "pdf_folder_merger_summary.xlsx"
    summary_df.to_excel(summary_path, index=False)

    all_outputs.insert(0, str(summary_path))

    push_log(log_queue, "SUCCESS", f"Completed {len(summary_rows)} top-level folders")

    return {"output_files": all_outputs}