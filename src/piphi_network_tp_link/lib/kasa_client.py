from __future__ import annotations

from typing import Any

from kasa import Discover


def _safe_feature_value(value: Any) -> Any:
    try:
        if callable(value):
            return value()
        return value
    except Exception:
        return None


def _safe_enum_like(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "value"):
        return getattr(value, "value")
    return str(value)


def _normalize_feature(feature_id: str, feature: Any) -> dict[str, Any]:
    feature_type = _safe_enum_like(getattr(feature, "type", None)) or "unknown"
    category = _safe_enum_like(getattr(feature, "category", None))
    writable = bool(getattr(feature, "attribute_setter", None))

    return {
        "id": feature_id,
        "name": str(getattr(feature, "name", feature_id)),
        "type": str(feature_type),
        "category": category,
        "value": _safe_feature_value(getattr(feature, "value", None)),
        "unit": _safe_feature_value(getattr(feature, "unit", None)),
        "choices": _safe_feature_value(getattr(feature, "choices", None)),
        "range": _safe_feature_value(getattr(feature, "range", None)),
        "writable": writable,
    }


def _extract_features(device: Any) -> dict[str, dict[str, Any]]:
    features: dict[str, dict[str, Any]] = {}
    try:
        for key, feature in device.features.items():
            features[key] = _normalize_feature(key, feature)
    except Exception:
        features = {}
    return features


def _derive_capabilities_from_features(features: dict[str, dict[str, Any]]) -> list[str]:
    capabilities: set[str] = set()

    if "state" in features:
        capabilities.add("switch")

    for feature in features.values():
        feature_id = str(feature.get("id", "")).lower()
        feature_type = str(feature.get("type", "")).lower()
        unit = str(feature.get("unit", "")).lower()

        if "brightness" in feature_id or "dimming" in feature_id:
            capabilities.add("brightness")
        if "color_temp" in feature_id or "color temperature" in feature_id:
            capabilities.add("color_temperature")
        if "hsv" in feature_id or feature_id in {"hue", "saturation", "color"}:
            capabilities.add("color")
        if "power" in feature_id and "w" in unit:
            capabilities.add("power")
        if "temperature" in feature_id:
            capabilities.add("temperature")
        if "humidity" in feature_id:
            capabilities.add("humidity")
        if feature_type in {"number", "sensor", "binary_sensor"}:
            capabilities.add("telemetry")

    capabilities.add("refresh")
    return sorted(capabilities)


def _command_args_for_child(has_children: bool, args: list[str]) -> list[str]:
    if has_children:
        return ["child_id", *args]
    return args


def _has_writable_feature(features: dict[str, dict[str, Any]], candidates: list[str]) -> bool:
    for candidate in candidates:
        feature = features.get(candidate)
        if feature and feature.get("writable"):
            return True
    return False


def _build_supported_commands(device: Any, features: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    commands: list[dict[str, Any]] = [
        {"id": "refresh", "label": "Refresh", "args": []},
        {"id": "read_energy", "label": "Read Energy", "args": []},
    ]
    has_children = bool(getattr(device, "children", []))

    if hasattr(device, "turn_on"):
        commands.append(
            {
                "id": "turn_on",
                "label": "Turn On",
                "args": _command_args_for_child(has_children, []),
            }
        )
    if hasattr(device, "turn_off"):
        commands.append(
            {
                "id": "turn_off",
                "label": "Turn Off",
                "args": _command_args_for_child(has_children, []),
            }
        )
    if hasattr(device, "turn_on") and hasattr(device, "turn_off"):
        commands.append(
            {
                "id": "toggle",
                "label": "Toggle Power",
                "args": _command_args_for_child(has_children, []),
            }
        )

    if hasattr(device, "set_alias"):
        commands.append(
            {
                "id": "set_alias",
                "label": "Set Alias",
                "args": _command_args_for_child(has_children, ["alias"]),
            }
        )

    if hasattr(device, "reboot"):
        commands.append(
            {
                "id": "reboot",
                "label": "Reboot Device",
                "args": _command_args_for_child(has_children, ["delay"]),
            }
        )

    writable_features = [feature for feature in features.values() if feature.get("writable")]
    if writable_features:
        commands.append(
            {
                "id": "set_feature",
                "label": "Set Feature",
                "args": _command_args_for_child(has_children, ["feature_id", "value"]),
                "writable_features": [feature["id"] for feature in writable_features],
            }
        )
        commands.append(
            {
                "id": "feature_action",
                "label": "Feature Action",
                "args": _command_args_for_child(has_children, ["feature_id", "value"]),
                "writable_features": [feature["id"] for feature in writable_features],
            }
        )

    if _has_writable_feature(features, ["brightness", "dimming_level"]):
        commands.append(
            {
                "id": "set_brightness",
                "label": "Set Brightness",
                "args": _command_args_for_child(has_children, ["value"]),
            }
        )

    if _has_writable_feature(features, ["color_temperature", "color_temp"]):
        commands.append(
            {
                "id": "set_color_temperature",
                "label": "Set Color Temperature",
                "args": _command_args_for_child(has_children, ["value"]),
            }
        )

    if _has_writable_feature(features, ["hue", "saturation"]):
        commands.append(
            {
                "id": "set_hue_saturation",
                "label": "Set Hue/Saturation",
                "args": _command_args_for_child(has_children, ["hue", "saturation"]),
            }
        )

    return commands


async def _resolve_device(host: str, username: str | None = None, password: str | None = None) -> Any:
    device = await Discover.discover_single(
        host,
        discovery_timeout=5,
        username=username,
        password=password,
    )
    if device is None:
        raise RuntimeError(f"Unable to discover Kasa device at host '{host}'")
    await device.update()
    return device


def _resolve_command_target(device: Any, args: dict[str, Any]) -> Any:
    child_id = str(args.get("child_id") or "").strip()
    if not child_id:
        return device

    child = device.get_child_device(child_id)
    if child is None:
        available = [
            str(getattr(child_device, "device_id", "")).strip() or str(getattr(child_device, "alias", ""))
            for child_device in getattr(device, "children", [])
        ]
        raise RuntimeError(
            f"Child '{child_id}' not found. Available children: {', '.join([v for v in available if v])}"
        )
    return child


def _resolve_writable_feature(target: Any, feature_id: str, candidates: list[str] | None = None) -> Any:
    if feature_id:
        feature = target.features.get(feature_id)
        if feature is None:
            raise RuntimeError(
                f"Feature '{feature_id}' not found. Available: {', '.join(target.features.keys())}"
            )
        if not getattr(feature, "attribute_setter", None):
            raise RuntimeError(f"Feature '{feature_id}' is read-only")
        return feature

    candidates = candidates or []
    for candidate in candidates:
        feature = target.features.get(candidate)
        if feature and getattr(feature, "attribute_setter", None):
            return feature

    raise RuntimeError(
        "No writable feature matched candidates: " + ", ".join(candidates)
    )


def _to_int(value: Any, arg_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Invalid integer for '{arg_name}': {value}") from exc


def _serialize_child(child: Any) -> dict[str, Any]:
    child_features = _extract_features(child)
    return {
        "id": str(getattr(child, "device_id", "") or getattr(child, "alias", "")),
        "alias": getattr(child, "alias", None),
        "model": getattr(child, "model", None),
        "is_on": bool(getattr(child, "is_on", False)),
        "features": child_features,
        "capabilities": _derive_capabilities_from_features(child_features),
        "supported_commands": _build_supported_commands(child, child_features),
    }


def _serialize_device(device: Any) -> dict[str, Any]:
    features = _extract_features(device)
    children = [_serialize_child(child) for child in getattr(device, "children", [])]

    signal = getattr(device, "rssi", None)
    if signal is None:
        signal = getattr(device, "signal_level", None)

    return {
        "host": device.host,
        "name": device.alias,
        "alias": device.alias,
        "model": device.model,
        "is_on": bool(getattr(device, "is_on", False)),
        "device_type": str(device.device_type),
        "mac": device.mac,
        "signal_strength": signal,
        "sys_info": device.sys_info,
        "features": features,
        "capabilities": _derive_capabilities_from_features(features),
        "commands": _build_supported_commands(device, features),
        "supported_commands": _build_supported_commands(device, features),
        "children": children,
    }


async def discover_devices() -> list[dict[str, Any]]:
    found = await Discover.discover(discovery_timeout=5)
    devices: list[dict[str, Any]] = []

    for _, device in found.items():
        await device.update()
        devices.append(_serialize_device(device))

    return devices


async def fetch_device_state(host: str, username: str | None = None, password: str | None = None) -> dict[str, Any]:
    device = await _resolve_device(host=host, username=username, password=password)
    return _serialize_device(device)


async def execute_device_command(
    *,
    host: str,
    command: str,
    args: dict[str, Any] | None = None,
    username: str | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    args = args or {}
    device = await _resolve_device(host=host, username=username, password=password)
    target = _resolve_command_target(device, args)

    if command == "turn_on":
        if not hasattr(target, "turn_on"):
            raise RuntimeError("This device does not support turn_on")
        await target.turn_on()
    elif command == "turn_off":
        if not hasattr(target, "turn_off"):
            raise RuntimeError("This device does not support turn_off")
        await target.turn_off()
    elif command == "toggle":
        if not hasattr(target, "turn_on") or not hasattr(target, "turn_off"):
            raise RuntimeError("This device does not support toggle")
        if bool(getattr(target, "is_on", False)):
            await target.turn_off()
        else:
            await target.turn_on()
    elif command == "set_alias":
        alias = str(args.get("alias") or "").strip()
        if not alias:
            raise RuntimeError("Missing required arg 'alias'")
        if not hasattr(target, "set_alias"):
            raise RuntimeError("This device does not support set_alias")
        await target.set_alias(alias)
    elif command == "reboot":
        delay = _to_int(args.get("delay", 1), "delay")
        if not hasattr(target, "reboot"):
            raise RuntimeError("This device does not support reboot")
        await target.reboot(delay=delay)
    elif command in {"refresh", "read_energy"}:
        pass
    elif command == "set_feature":
        feature_id = str(args.get("feature_id") or "").strip()
        if not feature_id:
            raise RuntimeError("Missing required arg 'feature_id'")
        if "value" not in args:
            raise RuntimeError("Missing required arg 'value' for set_feature")

        feature = _resolve_writable_feature(target, feature_id=feature_id)
        await feature.set_value(args.get("value"))
    elif command == "feature_action":
        feature_id = str(args.get("feature_id") or "").strip()
        if not feature_id:
            raise RuntimeError("Missing required arg 'feature_id'")

        feature = _resolve_writable_feature(target, feature_id=feature_id)
        await feature.set_value(args.get("value", None))
    elif command == "set_brightness":
        feature = _resolve_writable_feature(
            target,
            feature_id="",
            candidates=["brightness", "dimming_level"],
        )
        await feature.set_value(_to_int(args.get("value"), "value"))
    elif command == "set_color_temperature":
        feature = _resolve_writable_feature(
            target,
            feature_id="",
            candidates=["color_temperature", "color_temp"],
        )
        await feature.set_value(_to_int(args.get("value"), "value"))
    elif command == "set_hue_saturation":
        hue_feature = _resolve_writable_feature(target, feature_id="", candidates=["hue"])
        sat_feature = _resolve_writable_feature(target, feature_id="", candidates=["saturation"])
        await hue_feature.set_value(_to_int(args.get("hue"), "hue"))
        await sat_feature.set_value(_to_int(args.get("saturation"), "saturation"))
    else:
        raise RuntimeError(f"Unsupported command '{command}'")

    await device.update()
    return _serialize_device(device)
