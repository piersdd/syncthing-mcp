"""Pydantic input models for Syncthing MCP tools."""

from pydantic import BaseModel, ConfigDict, Field


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instance: str | None = Field(
        None, description="Instance name. Omit if only one instance is configured."
    )


class FolderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(
        ..., description="Syncthing folder ID (e.g. 'abcd-1234')", min_length=1
    )
    instance: str | None = Field(None, description="Instance name")


class DeviceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    device_id: str = Field(
        ...,
        description="Syncthing device ID (long alphanumeric string with dashes)",
        min_length=1,
    )
    instance: str | None = Field(None, description="Instance name")


class FolderDeviceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(..., description="Syncthing folder ID", min_length=1)
    device_id: str = Field(..., description="Syncthing device ID", min_length=1)
    instance: str | None = Field(None, description="Instance name")


class PauseFolderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(
        ..., description="Syncthing folder ID to pause/resume", min_length=1
    )
    instance: str | None = Field(None, description="Instance name")


class AcceptDeviceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    device_id: str = Field(
        ..., description="Device ID to accept (from pending list)", min_length=1
    )
    name: str | None = Field(
        None,
        description="Friendly name to assign. If omitted, uses the name from the pending request.",
    )
    instance: str | None = Field(None, description="Instance name")


class AcceptFolderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(
        ..., description="Folder ID to accept (from pending list)", min_length=1
    )
    path: str | None = Field(
        None,
        description="Local path for the folder. If omitted, uses Syncthing's default path.",
    )
    instance: str | None = Field(None, description="Instance name")


class RejectFolderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(
        ..., description="Folder ID to reject", min_length=1
    )
    device_id: str | None = Field(
        None,
        description="Device ID that offered the folder. If omitted, rejects from all devices.",
    )
    instance: str | None = Field(None, description="Instance name")


class SetIgnoresInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(..., description="Folder ID", min_length=1)
    patterns: list[str] = Field(
        ...,
        description="List of ignore patterns (e.g. ['*.tmp', '.DS_Store', '// #include'])",
    )
    instance: str | None = Field(None, description="Instance name")


class SetDefaultIgnoresInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lines: list[str] = Field(
        ...,
        description="Default ignore patterns for new folders (e.g. ['.DS_Store', 'Thumbs.db'])",
    )
    instance: str | None = Field(None, description="Instance name")


# --- New models for added tools ---


class BrowseFolderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(..., description="Syncthing folder ID", min_length=1)
    prefix: str | None = Field(
        None,
        description="Path prefix to browse (e.g. 'Documents/reports'). Omit for root.",
    )
    levels: int | None = Field(
        None,
        description="How many directory levels deep to return (default: 1).",
        ge=0,
    )
    instance: str | None = Field(None, description="Instance name")


class FileInfoInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(..., description="Syncthing folder ID", min_length=1)
    file_path: str = Field(
        ..., description="Relative path of the file within the folder", min_length=1
    )
    instance: str | None = Field(None, description="Instance name")


class FolderNeedInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(..., description="Syncthing folder ID", min_length=1)
    page: int = Field(1, description="Page number (1-based)", ge=1)
    per_page: int = Field(50, description="Items per page", ge=1, le=500)
    instance: str | None = Field(None, description="Instance name")
