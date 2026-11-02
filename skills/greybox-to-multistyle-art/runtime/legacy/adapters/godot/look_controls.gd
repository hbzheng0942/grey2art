extends RefCounted
# Optional experiment controls. Empty input preserves the historical adapter.
static func read_controls() -> Dictionary:
	var path: String = OS.get_environment("HOLE_ART_CONTROLS")
	if path.is_empty(): return {}
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(path))
	if not parsed is Dictionary:
		push_error("Invalid look controls: " + path)
		return {}
	return parsed

static func asset_controls(controls: Dictionary, spec: Dictionary) -> Dictionary:
	var result: Dictionary = {}
	var assembly: Dictionary = controls.get("assembly", {})
	result.merge(assembly.get("regions", {}).get(spec.get("regionId", ""), {}), true)
	result.merge(assembly.get("assets", {}).get(spec.get("assetKey", ""), {}), true)
	return result
