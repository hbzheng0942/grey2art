"""Upload local Lux3D inputs through the public Asset upload API."""

import argparse
import hashlib
import json
import math
import os
import pathlib
import sys
import tempfile
import time

import requests

import lux3d_client


REGION_BASE_URLS = {
    "cn": "https://api.aholo3d.cn",
    "international": "https://api.aholo.ai/global",
}
TERMINAL_SUCCESS = 5
TERMINAL_FAILURES = {6, 8}
DEFAULT_TIMEOUT = 30
DEFAULT_POLL_ATTEMPTS = 120
DEFAULT_POLL_INTERVAL = 1.0


def normalize_region(region=None):
    value = region or os.environ.get("LUX3D_REGION", "cn")
    aliases = {
        "cn": "cn",
        "china": "cn",
        "domestic": "cn",
        "international": "international",
        "global": "international",
        "intl": "international",
    }
    normalized = str(value).strip().lower()
    if normalized not in aliases:
        raise ValueError("region must be 'cn' or 'international'")
    return aliases[normalized]


def get_api_key(region, *, api_key=None, credential_provider=None):
    """Reuse the generation client's region-bound credential policy."""
    return lux3d_client.validate_api_key(
        normalize_region(region),
        api_key=api_key,
        credential_provider=credential_provider,
    )


def validate_file(file_path):
    path = pathlib.Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    if not path.is_file():
        raise ValueError(f"Input path is not a file: {path}")
    size = path.stat().st_size
    if size <= 0:
        raise ValueError(f"Input file is empty: {path}")
    return path, size


def file_md5(path, chunk_size=1024 * 1024):
    digest = hashlib.md5()
    with path.open("rb") as file_obj:
        while True:
            chunk = file_obj.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _request(session, method, url, *, retries=1, timeout=DEFAULT_TIMEOUT, **kwargs):
    if not isinstance(retries, int) or isinstance(retries, bool) or retries < 1:
        raise ValueError("retries must be a positive integer")
    last_error = None
    for attempt in range(retries):
        try:
            response = session.request(method, url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return response
        except (requests.Timeout, requests.RequestException) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(1)
    raise RuntimeError(
        f"Asset request failed after {retries} attempts: {last_error}"
    ) from last_error


def _response_data(response):
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Asset API returned invalid JSON: {response.text}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Asset API response must be a JSON object")
    if "c" in payload:
        code = payload.get("c")
        if code not in (None, "", 0, "0"):
            raise RuntimeError(
                f"Asset API error: {payload.get('m') or 'unknown error'} (code={code})"
            )
        data = payload.get("d") or {}
    else:
        data = payload
    if not isinstance(data, dict):
        raise RuntimeError("Asset API response data must be a JSON object")
    return data


def get_upload_token(
    session,
    region,
    timeout=DEFAULT_TIMEOUT,
    *,
    api_key=None,
    credential_provider=None,
):
    base_url = REGION_BASE_URLS[normalize_region(region)]
    response = _request(
        session,
        "GET",
        f"{base_url}/asset/v1/token",
        retries=3,
        timeout=timeout,
        headers={
            "Authorization": get_api_key(
                region,
                api_key=api_key,
                credential_provider=credential_provider,
            )
        },
    )
    data = _response_data(response)
    ous_token = data.get("ousToken")
    global_domain = data.get("globalDomain")
    try:
        block_size = int(data.get("blockSize"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Asset token response has invalid blockSize") from exc
    if not isinstance(ous_token, str) or not ous_token.strip():
        raise RuntimeError("Asset token response is missing ousToken")
    if not isinstance(global_domain, str) or not global_domain.startswith("https://"):
        raise RuntimeError("Asset token response has invalid globalDomain")
    if block_size <= 0:
        raise RuntimeError("Asset token response blockSize must be positive")
    return {
        "ousToken": ous_token.strip(),
        "globalDomain": global_domain.rstrip("/"),
        "blockSize": block_size,
    }


def parse_lack_blocks(value, total_blocks):
    if not isinstance(total_blocks, int) or total_blocks < 1:
        raise ValueError("total_blocks must be a positive integer")
    if value in (None, "", []):
        return list(range(1, total_blocks + 1))
    if isinstance(value, list):
        raw_parts = value
    elif isinstance(value, str):
        raw_parts = [part.strip() for part in value.split(",") if part.strip()]
    else:
        raise RuntimeError("lackBlocks must be a string or list")
    blocks = set()
    for part in raw_parts:
        if isinstance(part, int) and not isinstance(part, bool):
            start = end = part
        else:
            text = str(part).strip()
            if "-" in text:
                pieces = text.split("-", 1)
                try:
                    start, end = int(pieces[0]), int(pieces[1])
                except ValueError as exc:
                    raise RuntimeError(f"Invalid lackBlocks range: {text}") from exc
            else:
                try:
                    start = end = int(text)
                except ValueError as exc:
                    raise RuntimeError(f"Invalid lackBlocks item: {text}") from exc
        if start < 1 or end < start or end > total_blocks:
            raise RuntimeError(
                f"lackBlocks range {start}-{end} is outside 1-{total_blocks}"
            )
        blocks.update(range(start, end + 1))
    return sorted(blocks)


def _single_upload(session, path, checksum, token, timeout):
    url = token["globalDomain"] + "/ous/api/v2/single/upload"
    with path.open("rb") as file_obj:
        response = _request(
            session,
            "POST",
            url,
            retries=1,
            timeout=timeout,
            headers={"ous-token-v2": token["ousToken"]},
            files={"file": (path.name, file_obj)},
            data={"md5": checksum},
        )
    return _response_data(response)


def _init_block_upload(session, path, size, checksum, token, timeout):
    total_blocks = int(math.ceil(size / token["blockSize"]))
    response = _request(
        session,
        "POST",
        token["globalDomain"] + "/ous/api/v2/block/upload/init",
        retries=1,
        timeout=timeout,
        headers={"ous-token-v2": token["ousToken"]},
        data={
            "md5": checksum,
            "blocks": total_blocks,
            "size": size,
            "name": path.name,
        },
    )
    return total_blocks, _response_data(response)


def _upload_blocks(session, path, block_size, blocks, token, timeout):
    with path.open("rb") as file_obj:
        for block in blocks:
            file_obj.seek((block - 1) * block_size)
            content = file_obj.read(block_size)
            if not content:
                raise RuntimeError(f"Block {block} is empty")
            response = _request(
                session,
                "POST",
                token["globalDomain"] + "/ous/api/v2/block/upload/part",
                retries=1,
                timeout=timeout,
                headers={"ous-token-v2": token["ousToken"]},
                files={"file": (f"{path.name}.part-{block}", content)},
                data={"block": block},
            )
            _response_data(response)


def _validate_poll_options(poll_attempts, poll_interval, timeout):
    """Reject invalid polling options before any upload request. Author: yinjie."""
    if type(poll_attempts) is not int or poll_attempts < 1:
        raise ValueError("poll_attempts must be a positive integer")
    for name, value, minimum in (
        ("poll_interval", poll_interval, 0.2), ("timeout", timeout, 0),
    ):
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or value < minimum
            or (name == "timeout" and value == 0)
        ):
            raise ValueError(
                f"{name} must be finite and "
                + ("positive" if name == "timeout" else "at least 0.2 seconds")
            )


def poll_upload(
    session,
    token,
    *,
    poll_attempts=DEFAULT_POLL_ATTEMPTS,
    poll_interval=DEFAULT_POLL_INTERVAL,
    timeout=DEFAULT_TIMEOUT,
    sleep_fn=time.sleep,
):
    _validate_poll_options(poll_attempts, poll_interval, timeout)
    url = token["globalDomain"] + "/ous/api/v2/upload/status"
    for attempt in range(poll_attempts):
        response = _request(
            session,
            "GET",
            url,
            retries=3,
            timeout=timeout,
            headers={"ous-token-v2": token["ousToken"]},
        )
        data = _response_data(response)
        status = data.get("status")
        if status == TERMINAL_SUCCESS:
            result = {
                key: data.get(key)
                for key in ("status", "url", "uploadKey", "md5", "obsTaskId")
                if data.get(key) is not None
            }
            if not isinstance(result.get("url"), str) or not result["url"].startswith(
                ("http://", "https://")
            ):
                raise RuntimeError("Successful Asset upload is missing a valid url")
            return result
        if status in TERMINAL_FAILURES:
            raise RuntimeError(f"Asset upload failed with status {status}: {data}")
        if attempt + 1 < poll_attempts:
            sleep_fn(poll_interval)
    raise TimeoutError("Asset upload did not finish before the polling limit")


def upload_file(
    file_path,
    *,
    region=None,
    poll_attempts=DEFAULT_POLL_ATTEMPTS,
    poll_interval=DEFAULT_POLL_INTERVAL,
    timeout=DEFAULT_TIMEOUT,
    session=None,
    sleep_fn=time.sleep,
    api_key=None,
    credential_provider=None,
):
    _validate_poll_options(poll_attempts, poll_interval, timeout)
    path, size = validate_file(file_path)
    region = normalize_region(region)
    checksum = file_md5(path)
    owned_session = session is None
    session = session or requests.Session()
    try:
        token = get_upload_token(
            session,
            region,
            timeout=timeout,
            api_key=api_key,
            credential_provider=credential_provider,
        )
        if size <= token["blockSize"]:
            _single_upload(session, path, checksum, token, timeout)
            upload_mode = "single"
        else:
            total_blocks, init_data = _init_block_upload(
                session, path, size, checksum, token, timeout
            )
            if not bool(init_data.get("deduplicated")):
                blocks = parse_lack_blocks(init_data.get("lackBlocks"), total_blocks)
                _upload_blocks(
                    session, path, token["blockSize"], blocks, token, timeout
                )
            upload_mode = "block"
        result = poll_upload(
            session,
            token,
            poll_attempts=poll_attempts,
            poll_interval=poll_interval,
            timeout=timeout,
            sleep_fn=sleep_fn,
        )
        result.update(
            {
                "region": region,
                "localPath": str(path),
                "size": size,
                "sourceMd5": checksum,
                "uploadMode": upload_mode,
            }
        )
        return result
    finally:
        if owned_session:
            session.close()


def write_json_atomic(path, payload):
    target = pathlib.Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file_obj:
            json.dump(payload, file_obj, ensure_ascii=False, indent=2)
            file_obj.write("\n")
        os.replace(temporary, target)
    except Exception:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise


def build_parser():
    parser = argparse.ArgumentParser(description="Upload a local Lux3D input asset.")
    subparsers = parser.add_subparsers(dest="command")
    upload = subparsers.add_parser("upload")
    upload.add_argument("file_path")
    upload.add_argument("--region", choices=["cn", "international"])
    upload.add_argument("--poll-attempts", type=int, default=DEFAULT_POLL_ATTEMPTS)
    upload.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL)
    upload.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    upload.add_argument("--json-output")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.command != "upload":
        parser.print_help()
        raise SystemExit(1)
    result = upload_file(
        args.file_path,
        region=args.region,
        poll_attempts=args.poll_attempts,
        poll_interval=args.poll_interval,
        timeout=args.timeout,
    )
    if args.json_output:
        write_json_atomic(args.json_output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, ValueError, RuntimeError, TimeoutError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1)
