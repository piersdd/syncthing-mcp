"""Pydantic input models for Syncthing MCP tools."""

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
#  Read-oriented base models (include concise toggle for token efficiency)
# ---------------------------------------------------------------------------


class ReadParams(BaseModel):
    """Base for read-only tools — includes output-format flag."""

    model_config = ConfigDict(extra="forbid")
    instance: str | None = Field(
        None, description="Instance name. Omit if only one instance is configured."
    )
    concise: bool = Field(
        True,
        description="Compact output (default). Set false for full details.",
    )


class FolderReadParams(ReadParams):
    """Read tool that targets a single folder."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(
        ..., description="Syncthing folder ID (e.g. 'abcd-1234')", min_length=1
    )


class DeviceReadParams(ReadParams):
    """Read tool that targets a single device."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    device_id: str = Field(
        ...,
        description="Syncthing device ID (long alphanumeric string with dashes)",
        min_length=1,
    )


class FolderDeviceReadParams(ReadParams):
    """Read tool targeting a folder + device pair."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(..., description="Syncthing folder ID", min_length=1)
    device_id: str = Field(..., description="Syncthing device ID", min_length=1)


# ---------------------------------------------------------------------------
#  Write-oriented models (no concise flag — output is always minimal)
# ---------------------------------------------------------------------------


class WriteParams(BaseModel):
    """Base for write/mutating tools."""

    model_config = ConfigDict(extra="forbid")
    instance: str | None = Field(
        None, description="Instance name. Omit if only one instance is configured."
    )


class FolderWriteParams(WriteParams):
    """Write tool that targets a single folder."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(
        ..., description="Syncthing folder ID", min_length=1
    )


class DeviceWriteParams(WriteParams):
    """Write tool that targets a single device."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    device_id: str = Field(
        ..., description="Syncthing device ID", min_length=1
    )


# ---------------------------------------------------------------------------
#  Specialised input models
# ---------------------------------------------------------------------------


class AcceptDeviceInput(WriteParams):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    device_id: str = Field(
        ..., description="Device ID to accept (from pending list)", min_length=1
    )
    name: str | None = Field(
        None,
        description="Friendly name to assign. If omitted, uses the name from the pending request.",
    )


class AcceptFolderInput(WriteParams):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(
        ..., description="Folder ID to accept (from pending list)", min_length=1
    )
    path: str | None = Field(
        None,
        description="Local path for the folder. If omitted, uses Syncthing's default path.",
    )


class RejectFolderInput(WriteParams):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(
        ..., description="Folder ID to reject", min_length=1
    )
    device_id: str | None = Field(
        None,
        description="Device ID that offered the folder. If omitted, rejects from all devices.",
    )


class SetIgnoresInput(WriteParams):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(..., description="Folder ID", min_length=1)
    patterns: list[str] = Field(
        ...,
        description="List of ignore patterns (e.g. ['*.tmp', '.DS_Store', '// #include'])",
    )


class SetDefaultIgnoresInput(WriteParams):
    model_config = ConfigDict(extra="forbid")
    lines: list[str] = Field(
        ...,
        description="Default ignore patterns for new folders (e.g. ['.DS_Store', 'Thumbs.db'])",
    )


# ---------------------------------------------------------------------------
#  File-level query models
# ---------------------------------------------------------------------------


class BrowseFolderInput(ReadParams):
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


class FileInfoInput(ReadParams):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(..., description="Syncthing folder ID", min_length=1)
    file_path: str = Field(
        ..., description="Relative path of the file within the folder", min_length=1
    )


class FolderNeedInput(ReadParams):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(..., description="Syncthing folder ID", min_length=1)
    page: int = Field(1, description="Page number (1-based)", ge=1)
    per_page: int = Field(50, description="Items per page", ge=1, le=500)


class RemoteNeedInput(ReadParams):
    """Query files a remote device still needs for a folder."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(..., description="Syncthing folder ID", min_length=1)
    device_id: str = Field(..., description="Remote device ID", min_length=1)
    page: int = Field(1, description="Page number (1-based)", ge=1)
    per_page: int = Field(50, description="Items per page", ge=1, le=500)


# ---------------------------------------------------------------------------
#  Backward-compatible aliases (referenced by existing tests)
# ---------------------------------------------------------------------------

EmptyInput = ReadParams
FolderInput = FolderReadParams
DeviceInput = DeviceReadParams
PauseFolderInput = FolderWriteParams
FolderDeviceInput = FolderDeviceReadParams
