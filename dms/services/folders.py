from typing import Optional

from dms.models import Folder, Department, Document


def get_or_create_folder(
    *,
    department: Department,
    name: str,
    parent: Optional[Folder] = None,
) -> Folder:
    name = (name or "").strip()
    if not name:
        raise ValueError("Folder name is empty")

    folder, _ = Folder.objects.get_or_create(
        department=department,
        parent=parent,
        name=name,
    )
    return folder


def get_or_create_folder_tree(
    *,
    department: Department,
    parent_folder: Optional[Folder] = None,
    folder_name: Optional[str] = None,
    subfolder_name: Optional[str] = None,
) -> Optional[Folder]:

    current = parent_folder

    folder_name = (folder_name or "").strip()
    subfolder_name = (subfolder_name or "").strip()

    # 1. Новая папка
    if folder_name:
        current = get_or_create_folder(
            department=department,
            name=folder_name,
            parent=current,
        )

    # 2. Подпапка
    if subfolder_name:
        if not current:
            raise ValueError("Subfolder requires a parent folder")

        current = get_or_create_folder(
            department=department,
            name=subfolder_name,
            parent=current,
        )

    return current



def attach_document_to_folder(
    *,
    document: Document,
    folder: Optional[Folder],
) -> Document:
    document.folder = folder
    document.save(update_fields=["folder"])
    return document


