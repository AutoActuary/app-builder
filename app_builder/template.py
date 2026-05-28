from __future__ import annotations

import html
import shutil
import textwrap
import types
from collections.abc import Mapping
from dataclasses import Field, MISSING, fields, is_dataclass
from pathlib import Path
from typing import Any, Union, cast, get_args, get_origin, get_type_hints

import yaml

from .project import find_project_root
from .schema import AppBuilderConfig
from .schema_core import REQUIRED, example_mapping, get_config_meta

_NONE_TYPE = type(None)
TEMPLATE_SNAPSHOT_PATH = (
    Path(__file__).resolve().parent / "assets" / "app_builder_template.yaml"
)


def render_config_template_yaml() -> str:
    """Render the commented example config from schema metadata."""

    values = example_mapping(AppBuilderConfig)
    lines = [
        "# app_builder.yaml",
        "# Generated from app_builder.schema metadata.",
        "# Required and common optional fields contain examples; replace them for your app.",
        "# String values can reference ${ENV.NAME}, ${GIT.DESCRIBE}, ${GIT.COMMIT},",
        "# ${GIT.SHORT_COMMIT}, ${GIT.BRANCH}, ${GIT.TAG}, ${GIT.IS_DIRTY},",
        "# ${APP.VERSION}, and ${CONFIG.path.to.value}.",
        "# Interpolation is string-only and runs before schema validation.",
        "# Keep app_builder_version literal; the version dispatcher reads it before",
        "# the full 1.x config interpolation layer is loaded.",
    ]
    _emit_dataclass_yaml(AppBuilderConfig, values, lines, indent=0)
    return _finish_text(lines)


def render_config_reference_markdown() -> str:
    """Render human-readable config docs from the same metadata as the template."""

    lines = [
        "# app_builder.yaml Configuration Reference",
        "",
        "Generated from `app_builder.schema` metadata. `app-builder init` renders "
        "its example YAML from the same source.",
        "",
        "Required fields can appear in examples without defaults. That means users "
        "must provide project-specific values; the loader still rejects missing "
        "required values, unknown keys, unsupported shapes, and explicit `null` "
        "where a field is not nullable.",
        "",
        "## Complete app_builder.yaml Template",
        "",
        "This is the full generated template. Required fields contain example "
        "values that you must replace for your app. Optional fields show their "
        "defaults or empty lists.",
        "",
        "```yaml",
        render_config_template_yaml().rstrip(),
        "```",
        "",
        "String values are interpolated before schema validation. Supported "
        "variables are `${ENV.NAME}`, `${GIT.DESCRIBE}`, `${GIT.COMMIT}`, "
        "`${GIT.SHORT_COMMIT}`, `${GIT.BRANCH}`, `${GIT.TAG}`, "
        "`${GIT.IS_DIRTY}`, `${APP.VERSION}`, and `${CONFIG.path.to.value}`. "
        "Interpolation is string-only; references to lists or mappings are "
        "rejected.",
        "",
        "## String Interpolation",
        "",
        "Use `${...}` inside YAML string values when a config value should be "
        "derived from the environment, git, the app-builder release version, or "
        "another config string. Interpolation happens after YAML parsing and "
        "before dataclass schema validation, so the final expanded value is what "
        "the schema sees.",
        "",
        "| Variable | Value | Notes |",
        "| --- | --- | --- |",
        "| `${ENV.NAME}` | Environment variable from the running process. | Lookup is "
        "case-insensitive as a Windows convenience. Missing variables fail the "
        "config load. |",
        "| `${GIT.DESCRIBE}` | `git describe --tags --always --dirty`, with the "
        "same fallback as app-builder's version detection. | Good for "
        "version-from-tag config values. |",
        "| `${GIT.COMMIT}` | Full current commit hash. | Fails if git cannot read "
        "the repository. |",
        "| `${GIT.SHORT_COMMIT}` | Short current commit hash. | Fails if git cannot "
        "read the repository. |",
        "| `${GIT.BRANCH}` | Current branch name. | Empty string when HEAD is "
        "detached or no branch is available. |",
        "| `${GIT.TAG}` | Exact tag at HEAD. | Empty string when HEAD is not exactly "
        "on a tag. |",
        "| `${GIT.IS_DIRTY}` | `true` when `git status --porcelain` has output, "
        "otherwise `false`. | Fails if git cannot read the repository. |",
        "| `${APP.VERSION}` | The app-builder release version. | Honors "
        "`--version`; otherwise uses app-builder's git-based version detection. |",
        "| `${CONFIG.path.to.value}` | Another resolved string value in the same "
        "config. | Resolves recursively. Circular references, missing paths, and "
        "references to non-string values fail. List indexes are allowed in the "
        "path, but the final target must be a string. |",
        "",
        "`app_builder_version` is the exception to the usual interpolation "
        "surface. The command dispatcher reads that selector from plain YAML "
        "before importing the full 1.x app-builder package, so keep it literal "
        "(`current`, a branch, a tag, or a commit).",
        "",
        "For Windows paths, single-quoted YAML strings are usually easiest "
        "because backslashes stay literal. If you use double-quoted YAML strings "
        "for Windows paths, write backslashes as `\\\\`.",
        "",
        "Use percent-style Windows variables such as `%localappdata%` for "
        "install paths that must resolve on the user's machine. `${ENV.*}` is "
        "resolved while building the release, so it bakes in the builder or CI "
        "environment.",
        "",
        "Example:",
        "",
        "```yaml",
        "installer:",
        '  name: "MyApp ${APP.VERSION}"',
        "  install_directory: '%localappdata%\\Acme\\${CONFIG.installer.name}'",
        "  paths:",
        "    include:",
        '      - "build/${APP.VERSION}"',
        "    remap:",
        '      - [README.md, "docs/${CONFIG.installer.name}.md"]',
        "```",
        "",
    ]
    _emit_dataclass_markdown("config", AppBuilderConfig, lines)
    lines.extend(
        [
            "## Command Values",
            "",
            "Hook fields are `list[list[string]]`. Each command is an argv list. "
            "Use an explicit shell argv, such as `[cmd, /c, ...]`, when shell "
            "behavior is required.",
            "",
            "When a hook command's `argv[0]` is a `.py` file, app-builder runs it "
            "with the Python runtime configured for the project, preferring "
            "`python_venv` and then `python_bundled`. That means a hook such as "
            "`[scripts/build.py]` does not need `python.exe` on PATH. Use an "
            "explicit argv such as `[python, script.py]` only when the target "
            "machine is expected to provide Python.",
            "",
        ]
    )
    return _finish_text(lines)


def render_help_config_reference_html() -> str:
    """Render the full config help block for the packaged HTML help page."""

    template = html.escape(render_config_template_yaml())
    lines = [
        '      <section id="config">',
        "        <h2>Configuration</h2>",
        "        <p>",
        "          <code>app_builder.yaml</code> is the contract for a project. The loader is strict: unknown keys",
        "          are rejected, legacy <code>application.yaml</code> shapes are rejected, and hook commands must be",
        "          argv lists. The complete shape below is generated from the same schema metadata as",
        "          <code>app-builder init</code>.",
        "        </p>",
        '        <div class="callout">',
        "          <p>",
        "            Start from the complete template when you are unsure. It shows every supported field, its",
        "            default when omitted, and the short help text attached to that config option.",
        "          </p>",
        "        </div>",
        "        <h3>Complete app_builder.yaml Template</h3>",
        "        <p>",
        "          This is the full generated template. Required fields contain example values that you must replace",
        "          for your app. Optional fields show their defaults or empty lists.",
        "        </p>",
        f"        <pre><code>{template}</code></pre>",
        "        <h3>How To Read The Reference</h3>",
        "        <table>",
        "          <thead>",
        "            <tr>",
        "              <th>Column</th>",
        "              <th>Meaning</th>",
        "            </tr>",
        "          </thead>",
        "          <tbody>",
        "            <tr><td>Field</td><td>The YAML key at that level.</td></tr>",
        "            <tr><td>Type</td><td>The accepted YAML shape after interpolation has run.</td></tr>",
        "            <tr><td>Required</td><td><code>yes</code> means you must provide it. <code>no</code> means app-builder supplies a default.</td></tr>",
        "            <tr><td>Default</td><td>The value used when the key is omitted. Nested mappings say to see their child defaults.</td></tr>",
        "            <tr><td>Example</td><td>A realistic value from the generated template.</td></tr>",
        "            <tr><td>What it does</td><td>The behavior controlled by the option.</td></tr>",
        "          </tbody>",
        "        </table>",
        "        <h3>Field Reference</h3>",
    ]
    _emit_dataclass_html("config", AppBuilderConfig, lines)
    lines.extend(
        [
            "        <h3>Command Values</h3>",
            "        <p>",
            "          Hook fields are <code>list[list[string]]</code>. Each command is an argv list. Use an",
            "          explicit shell argv, such as <code>[cmd.exe, /D, /C, ...]</code>, when shell behavior is",
            "          required.",
            "        </p>",
            "        <p>",
            "          When a hook command starts with an existing <code>.py</code> file, app-builder runs it with",
            "          the Python runtime configured for the project, preferring <code>python_venv</code> and then",
            "          <code>python_bundled</code>. A hook such as <code>[scripts/build.py]</code> does not need",
            "          <code>python.exe</code> on PATH. Use <code>[python, scripts/build.py]</code> only when",
            "          you deliberately want the machine's own <code>python</code>.",
            "        </p>",
            "      </section>",
        ]
    )
    return "\n".join(lines)


def initialize_project(start: Path, *, force: bool) -> Path:
    project_root = find_project_root(start)
    config_path = project_root / "app_builder.yaml"
    if config_path.exists() and not force:
        raise FileExistsError(
            f"{config_path} already exists. Use --force to overwrite it."
        )

    template_assets_dir = project_root / "application-templates"
    template_assets_dir.mkdir(exist_ok=True)
    package_assets_dir = Path(__file__).resolve().parent / "assets" / "templates"
    for asset in package_assets_dir.iterdir():
        if asset.is_file():
            shutil.copy2(asset, template_assets_dir / asset.name)

    config_path.write_text(render_config_template_yaml(), encoding="utf-8")
    return config_path


def _emit_dataclass_yaml(
    config_type: type[Any],
    values: Mapping[str, Any],
    lines: list[str],
    *,
    indent: int,
) -> None:
    hints = get_type_hints(config_type, include_extras=True)
    for index, field_ in enumerate(fields(config_type)):
        if index > 0:
            lines.append("")
        annotation = hints[field_.name]
        _append_comment(lines, _field_comment(field_, annotation), indent)
        _emit_named_yaml_value(
            lines,
            field_.name,
            annotation,
            values[field_.name],
            indent=indent,
        )


def _emit_named_yaml_value(
    lines: list[str],
    name: str,
    annotation: Any,
    value: Any,
    *,
    indent: int,
) -> None:
    prefix = " " * indent
    nested_type = _nested_dataclass_type(annotation)
    list_item_type = _list_dataclass_item_type(annotation)
    if nested_type is not None and isinstance(value, Mapping):
        lines.append(f"{prefix}{name}:")
        _emit_dataclass_yaml(nested_type, value, lines, indent=indent + 2)
    elif list_item_type is not None and isinstance(value, list):
        _emit_list_of_dataclass_values(lines, name, list_item_type, value, indent)
    else:
        _emit_generic_named_yaml_value(lines, name, value, indent)


def _emit_list_of_dataclass_values(
    lines: list[str],
    name: str,
    item_type: type[Any],
    values: list[Any],
    indent: int,
) -> None:
    prefix = " " * indent
    if not values:
        lines.append(f"{prefix}{name}: []")
        return
    lines.append(f"{prefix}{name}:")
    for item in values:
        if not isinstance(item, Mapping):
            lines.append(f"{prefix}  - {_inline_yaml(item)}")
            continue
        _emit_dataclass_sequence_item(lines, item_type, item, indent + 2)


def _emit_dataclass_sequence_item(
    lines: list[str],
    item_type: type[Any],
    value: Mapping[str, Any],
    indent: int,
) -> None:
    prefix = " " * indent
    hints = get_type_hints(item_type, include_extras=True)
    item_fields = fields(item_type)
    first = True
    for field_ in item_fields:
        field_value = value[field_.name]
        annotation = hints[field_.name]
        nested_type = _nested_dataclass_type(annotation)
        list_item_type = _list_dataclass_item_type(annotation)
        multiline = (
            isinstance(field_value, Mapping)
            or _is_nonempty_block_list(field_value)
            or (nested_type is not None and field_value is not None)
            or (list_item_type is not None and bool(field_value))
        )
        field_prefix = f"{prefix}- " if first else f"{prefix}  "
        if multiline:
            lines.append(f"{field_prefix}{field_.name}:")
            _emit_generic_yaml_body(lines, field_value, indent + 4)
        else:
            lines.append(f"{field_prefix}{field_.name}: {_inline_yaml(field_value)}")
        first = False


def _emit_generic_named_yaml_value(
    lines: list[str],
    name: str,
    value: Any,
    indent: int,
) -> None:
    prefix = " " * indent
    if isinstance(value, Mapping):
        if not value:
            lines.append(f"{prefix}{name}: {{}}")
        else:
            lines.append(f"{prefix}{name}:")
            _emit_generic_yaml_body(lines, value, indent + 2)
    elif isinstance(value, list):
        if not value:
            lines.append(f"{prefix}{name}: []")
        else:
            lines.append(f"{prefix}{name}:")
            _emit_sequence_yaml_body(lines, value, indent + 2)
    else:
        lines.append(f"{prefix}{name}: {_inline_yaml(value)}")


def _emit_generic_yaml_body(lines: list[str], value: Any, indent: int) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _emit_generic_named_yaml_value(lines, str(key), item, indent)
    elif isinstance(value, list):
        _emit_sequence_yaml_body(lines, value, indent)
    else:
        lines.append(f"{' ' * indent}{_inline_yaml(value)}")


def _emit_sequence_yaml_body(lines: list[str], values: list[Any], indent: int) -> None:
    prefix = " " * indent
    for item in values:
        if isinstance(item, Mapping):
            lines.append(f"{prefix}-")
            _emit_generic_yaml_body(lines, item, indent + 2)
        elif _is_nonempty_block_list(item):
            lines.append(f"{prefix}-")
            _emit_sequence_yaml_body(lines, cast(list[Any], item), indent + 2)
        else:
            lines.append(f"{prefix}- {_inline_yaml(item)}")


def _emit_dataclass_markdown(
    path: str,
    config_type: type[Any],
    lines: list[str],
) -> None:
    title = "Top-Level Config" if path == "config" else f"`{path}`"
    lines.extend(
        [
            f"## {title}",
            "",
            "| Field | Type | Required | Default | Example | Description |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    hints = get_type_hints(config_type, include_extras=True)
    for field_ in fields(config_type):
        annotation = hints[field_.name]
        meta = get_config_meta(field_)
        lines.append(
            "| "
            + " | ".join(
                [
                    _markdown_cell(f"`{field_.name}`"),
                    _markdown_cell(f"`{_annotation_label(annotation)}`"),
                    "yes" if _is_required(field_) else "no",
                    _markdown_cell(_markdown_default(field_)),
                    _markdown_cell(_markdown_example(field_)),
                    _markdown_cell(meta.description or ""),
                ]
            )
            + " |"
        )
    lines.append("")

    for field_ in fields(config_type):
        annotation = hints[field_.name]
        nested_type = _nested_dataclass_type(annotation)
        list_item_type = _list_dataclass_item_type(annotation)
        if nested_type is not None:
            _emit_dataclass_markdown(f"{path}.{field_.name}", nested_type, lines)
        elif list_item_type is not None:
            _emit_dataclass_markdown(f"{path}.{field_.name}[]", list_item_type, lines)


def _emit_dataclass_html(
    path: str,
    config_type: type[Any],
    lines: list[str],
) -> None:
    title = "Top-Level Config" if path == "config" else path
    lines.extend(
        [
            f'        <h4 id="{_config_anchor(path)}">{_html(title)}</h4>',
            "        <table>",
            "          <thead>",
            "            <tr>",
            "              <th>Field</th>",
            "              <th>Type</th>",
            "              <th>Required</th>",
            "              <th>Default</th>",
            "              <th>Example</th>",
            "              <th>What it does</th>",
            "            </tr>",
            "          </thead>",
            "          <tbody>",
        ]
    )
    hints = get_type_hints(config_type, include_extras=True)
    for field_ in fields(config_type):
        annotation = hints[field_.name]
        meta = get_config_meta(field_)
        lines.extend(
            [
                "            <tr>",
                f"              <td><code>{_html(field_.name)}</code></td>",
                f"              <td><code>{_html(_annotation_label(annotation))}</code></td>",
                f"              <td>{'yes' if _is_required(field_) else 'no'}</td>",
                f"              <td>{_html_code_or_text(_default_summary_for_reference(field_))}</td>",
                f"              <td>{_html_code_or_text(_example_summary(field_))}</td>",
                f"              <td>{_html(meta.description or '')}</td>",
                "            </tr>",
            ]
        )
    lines.extend(
        [
            "          </tbody>",
            "        </table>",
        ]
    )

    for field_ in fields(config_type):
        annotation = hints[field_.name]
        nested_type = _nested_dataclass_type(annotation)
        list_item_type = _list_dataclass_item_type(annotation)
        if nested_type is not None:
            _emit_dataclass_html(f"{path}.{field_.name}", nested_type, lines)
        elif list_item_type is not None:
            _emit_dataclass_html(f"{path}.{field_.name}[]", list_item_type, lines)


def _field_comment(field_: Field[Any], annotation: Any) -> str:
    meta = get_config_meta(field_)
    status = "Required" if _is_required(field_) else "Optional"
    if _allows_none(annotation):
        status = f"{status}, nullable"
    comment = f"{status} {_annotation_label(annotation)}."
    if meta.description:
        comment = f"{comment} {meta.description}"
    default_text = _default_summary(field_)
    if default_text is not None:
        comment = f"{comment} Default if omitted: {default_text}."
    return comment


def _append_comment(lines: list[str], text: str, indent: int) -> None:
    prefix = " " * indent
    for line in textwrap.wrap(text, width=88 - indent):
        lines.append(f"{prefix}# {line}")


def _default_summary(field_: Field[Any]) -> str | None:
    if field_.default is not MISSING:
        return _inline_yaml(_plain_value(field_.default))
    if field_.default_factory is not MISSING:
        value = field_.default_factory()
        if is_dataclass(value):
            return f"{type(value).__name__} defaults"
        return _inline_yaml(_plain_value(value))
    return None


def _default_summary_for_reference(field_: Field[Any]) -> str | None:
    if field_.default_factory is not MISSING:
        value = field_.default_factory()
        if is_dataclass(value):
            return "see nested defaults"
    return _default_summary(field_)


def _example_summary(field_: Field[Any]) -> str | None:
    meta = get_config_meta(field_)
    if meta.example is not REQUIRED:
        return _inline_yaml(_plain_value(meta.example))
    if meta.example_factory is not None:
        return _inline_yaml(_plain_value(meta.example_factory()))
    return None


def _markdown_default(field_: Field[Any]) -> str:
    summary = _default_summary_for_reference(field_)
    if summary is None:
        return "required"
    return f"`{summary}`"


def _markdown_example(field_: Field[Any]) -> str:
    summary = _example_summary(field_)
    if summary is None:
        return ""
    return f"`{summary}`"


def _annotation_label(annotation: Any) -> str:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if annotation is Any:
        return "any"
    if annotation is str:
        return "string"
    if annotation is bool:
        return "boolean"
    if annotation is int:
        return "integer"
    if annotation is float:
        return "number"
    if _is_dataclass_type(annotation):
        return "mapping"
    if origin is list and len(args) == 1:
        return f"list[{_annotation_label(args[0])}]"
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return f"tuple[{_annotation_label(args[0])}, ...]"
        return "tuple[" + ", ".join(_annotation_label(arg) for arg in args) + "]"
    if _is_union(origin):
        return " | ".join(
            "null" if arg is _NONE_TYPE else _annotation_label(arg) for arg in args
        )
    return str(annotation).replace("typing.", "")


def _nested_dataclass_type(annotation: Any) -> type[Any] | None:
    if _is_dataclass_type(annotation):
        return cast(type[Any], annotation)
    origin = get_origin(annotation)
    args = get_args(annotation)
    if _is_union(origin):
        non_none = [arg for arg in args if arg is not _NONE_TYPE]
        if len(non_none) == 1 and _is_dataclass_type(non_none[0]):
            return cast(type[Any], non_none[0])
    return None


def _list_dataclass_item_type(annotation: Any) -> type[Any] | None:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is list and len(args) == 1 and _is_dataclass_type(args[0]):
        return cast(type[Any], args[0])
    return None


def _allows_none(annotation: Any) -> bool:
    origin = get_origin(annotation)
    return _is_union(origin) and _NONE_TYPE in get_args(annotation)


def _is_required(field_: Field[Any]) -> bool:
    return field_.default is MISSING and field_.default_factory is MISSING


def _is_union(origin: Any) -> bool:
    return origin is Union or origin is types.UnionType


def _is_dataclass_type(value: Any) -> bool:
    return isinstance(value, type) and is_dataclass(value)


def _is_nonempty_block_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and not _all_inline_items(value)


def _all_inline_items(values: list[Any]) -> bool:
    return all(not isinstance(item, (Mapping, list)) for item in values)


def _inline_yaml(value: Any) -> str:
    dumped = yaml.safe_dump(
        value,
        default_flow_style=True,
        sort_keys=False,
        width=4096,
    ).strip()
    lines = [line for line in dumped.splitlines() if line != "..."]
    return " ".join(lines) if lines else "null"


def _plain_value(value: Any) -> Any:
    if is_dataclass(value):
        return {
            field_.name: _plain_value(getattr(value, field_.name))
            for field_ in fields(value)
        }
    if isinstance(value, list):
        return [_plain_value(item) for item in value]
    if isinstance(value, tuple):
        return [_plain_value(item) for item in value]
    if isinstance(value, dict):
        return {_plain_value(key): _plain_value(item) for key, item in value.items()}
    return value


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


def _html(value: str) -> str:
    return html.escape(value, quote=True)


def _html_code_or_text(value: str | None) -> str:
    if value is None:
        return ""
    return f"<code>{_html(value)}</code>"


def _config_anchor(path: str) -> str:
    normalized = (
        path.replace("config", "config-reference", 1)
        .replace(".", "-")
        .replace("[", "")
        .replace("]", "")
    )
    return normalized


def _finish_text(lines: list[str]) -> str:
    return "\n".join(lines).rstrip() + "\n"
