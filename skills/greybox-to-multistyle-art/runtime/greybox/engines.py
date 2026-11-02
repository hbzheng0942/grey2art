"""Native engine dispatch. Historical plans without an engine remain Godot plans."""
from __future__ import annotations

from pathlib import Path
import re

from . import core


def name(plan=None, project=None):
    plan = plan or {}
    declarations = [plan.get("engine"), plan.get("workspace", {}).get("engine"),
                    plan.get("contract", {}).get("engine")]
    values = {v.get("name") if isinstance(v, dict) else v for v in declarations if v}
    core.require(len(values) <= 1, "Conflicting engine declarations")
    if values:
        result = values.pop()
    elif project and (Path(project) / "ProjectSettings/ProjectVersion.txt").is_file():
        core.require(not (Path(project) / "project.godot").exists(), "Ambiguous engine project; declare engine")
        result = "unity"
    else:
        result = "godot"
    core.require(result in {"godot", "unity"}, "No native execution adapter for engine: " + str(result))
    return result


def validate_scene(plan):
    scene = plan.get("contract", {}).get("scene")
    engine = name(plan)
    if engine == "godot":
        core.require(isinstance(scene, str) and scene.startswith("res://") and scene.endswith(".tscn"),
                     "contract.scene must identify the actual Godot scene")
    else:
        core.require(isinstance(scene, str) and scene.startswith("Assets/") and scene.endswith(".unity")
                     and ".." not in Path(scene).parts, "Unity contract.scene must identify an Assets/*.unity scene")
    return engine


def configuration_files(project, plan=None):
    root = Path(project).resolve()
    if name(plan, root) == "godot":
        return [root / "project.godot"]
    required = [root / "ProjectSettings/ProjectVersion.txt", root / "Packages/manifest.json"]
    optional = [root / "Packages/packages-lock.json", root / "ProjectSettings/GraphicsSettings.asset",
                root / "ProjectSettings/QualitySettings.asset", root / "ProjectSettings/ProjectSettings.asset",
                root / "ProjectSettings/EditorBuildSettings.asset"]
    return required + [p for p in optional if p.is_file()]


def dependency_snapshot(project, plan):
    if name(plan, project) == "godot":
        from . import godot
        return godot.dependency_snapshot(project, plan)
    from . import unity
    result = unity.dependency_snapshot(project, plan)
    if isinstance(result, dict):
        result = result.get("files", result.get("dependencies", []))
    if isinstance(result, dict):
        result = [{"path": str(core.resolve_input(p, project)), "sha256": h} for p, h in result.items()]
    core.require(isinstance(result, list), "Engine dependency adapter must return file records")
    records = {}
    for item in result:
        p = core.resolve_input(item["path"], project)
        core.require(p.is_file(), "Native dependency missing: " + str(p))
        records[str(p)] = {"path": str(p), "sha256": core.file_hash(p)}
    return [records[p] for p in sorted(records)]


def import_sidecar(path, engine):
    return Path(str(path) + (".meta" if engine == "unity" else ".import"))


def resource_path(path, project, plan=None):
    path, root = Path(path).resolve(), Path(project).resolve()
    if not core.inside(path, root):
        return str(path)
    relative = path.relative_to(root).as_posix()
    return "res://" + relative if name(plan, root) == "godot" else relative


def adapter(plan, project=None):
    if name(plan, project) == "godot":
        from . import godot
        return godot
    return UnityAdapter()


def validate_unity_owned(project, plan, style, artifact, item):
    """Admit only the adapter's exact non-workspace resource/tool roots."""
    root = Path(project).resolve()
    path = core.resolve_input(item["path"], root)
    if item.get("retention") == "canonical_tool" and item.get("role") == "tool":
        tools = root / "Assets/GreyboxArtRuntime"
        core.require(path != tools and core.inside(path, tools), "Unity tool ownership is outside its canonical root")
        return
    base = root / "Assets/Art/Greybox" / plan["id"] / style
    revision = core.resolve_input(artifact.get("output_root", ""), root)
    core.require(revision.parent == base and re.fullmatch(r"[0-9a-f]{16}", revision.name),
                 "Unity artifact revision is outside its declared plan/style")
    core.require(item.get("retention") == "canonical_revision" and path != revision and core.inside(path, revision),
                 "Unity ownership is outside its exact immutable revision")


class UnityAdapter:
    """Preserve the existing core adapter interface while using the Unity bridge."""
    @staticmethod
    def assemble(project, run_dir, plan, style, godot_path=None):
        from . import unity
        sid = style.get("id") if isinstance(style, dict) else style
        revision = core.digest({"plan": plan, "inputs": core.input_snapshot(project, plan)["sha256"],
                                "runtime": core.runtime_snapshot()["sha256"]})[:16]
        if plan.get("workspace"):
            from . import layout
            target = layout.runtime_root(project, plan, sid) / revision
        else:
            target = Path(project) / "Assets/Art/Greybox" / plan["id"] / sid / revision
        result = unity.run(project, "assemble", config={"plan": plan, "style_id": sid,
                           "scene": plan["contract"]["scene"], "output_root": str(target)},
                           output=Path(run_dir) / "unity" / sid, unity_bin=godot_path)
        artifact = result.get("artifact", result.get("result", result))
        core.require(artifact.get("entry_scene") and artifact.get("binding_digest"),
                     "Unity assembly did not return a complete native artifact")
        return artifact

    @staticmethod
    def validate(project, artifact, output_dir, godot_path=None):
        from . import unity
        result = unity.run(project, "validate", config={"artifact": artifact,
                           "scene": artifact["entry_scene"]}, output=output_dir, unity_bin=godot_path)
        return result.get("validation", result.get("result", result))

    @staticmethod
    def launch(project, artifact, godot_path=None):
        from . import unity
        return unity.launch(project, {"artifact": artifact, "scene": artifact["entry_scene"]},
                            unity_bin=godot_path)

    @staticmethod
    def import_resources(project, godot_path=None):
        from . import unity
        result = unity.run(project, "import", unity_bin=godot_path)
        return {**result, "passed": result.get("ok", False)}
