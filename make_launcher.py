#!/usr/bin/env python3
"""
Universal Standalone App Launcher Builder for Kindle 4 (K4NT / KDK 1.0)
Creates a signed, native .azw2 Kindle document for any shell script, app, or command.
"""

import os
import sys
import json
import struct
import base64
import hashlib
import zipfile
import argparse

from pyasn1.codec.der import decoder, encoder
from pyasn1_modules import rfc2315
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes


def patch_kindlet_class(data, cmd, work_dir, title_msg, timeout_msg, exit_msg):
    magic, minor, major, cp_count = struct.unpack('>IHHH', data[:10])
    pos = 10
    i = 1
    while i < cp_count:
        tag = data[pos]
        pos += 1
        if tag == 1:
            l = struct.unpack('>H', data[pos:pos+2])[0]
            pos += 2 + l
        elif tag in (7, 8):
            pos += 2
        elif tag in (3, 4):
            pos += 4
        elif tag in (5, 6):
            pos += 8
            i += 1
        elif tag in (9, 10, 11, 12):
            pos += 4
        i += 1

    cp_end = pos
    cmd_bytes = cmd.encode('utf-8')
    dir_bytes = work_dir.encode('utf-8')
    msg1_bytes = title_msg.encode('utf-8')
    msg2_bytes = timeout_msg.encode('utf-8')
    msg3_bytes = exit_msg.encode('utf-8')

    idx_cmd_utf8 = cp_count
    idx_cmd_str = cp_count + 1
    idx_dir_utf8 = cp_count + 2
    idx_dir_str = cp_count + 3
    idx_msg1_utf8 = cp_count + 4
    idx_msg1_str = cp_count + 5
    idx_msg2_utf8 = cp_count + 6
    idx_msg2_str = cp_count + 7
    idx_msg3_utf8 = cp_count + 8
    idx_msg3_str = cp_count + 9

    new_cp_entries = bytearray()
    for b, idx in [
        (cmd_bytes, idx_cmd_utf8),
        (dir_bytes, idx_dir_utf8),
        (msg1_bytes, idx_msg1_utf8),
        (msg2_bytes, idx_msg2_utf8),
        (msg3_bytes, idx_msg3_utf8)
    ]:
        new_cp_entries.append(1)
        new_cp_entries.extend(struct.pack('>H', len(b)) + b)
        new_cp_entries.append(8)
        new_cp_entries.extend(struct.pack('>H', idx))

    new_cp_count = cp_count + 10
    data_new = bytearray(data[:8])
    data_new.extend(struct.pack('>H', new_cp_count))
    data_new.extend(data[10:cp_end])
    data_new.extend(new_cp_entries)

    rest = bytearray(data[cp_end:])
    rpos = 6
    if_count = struct.unpack('>H', rest[rpos:rpos+2])[0]
    rpos += 2 + if_count * 2

    f_count = struct.unpack('>H', rest[rpos:rpos+2])[0]
    rpos += 2
    for _ in range(f_count):
        rpos += 6
        ac = struct.unpack('>H', rest[rpos:rpos+2])[0]
        rpos += 2
        for _ in range(ac):
            l = struct.unpack('>I', rest[rpos+2:rpos+6])[0]
            rpos += 6 + l

    m_count = struct.unpack('>H', rest[rpos:rpos+2])[0]
    rpos += 2
    for _ in range(m_count):
        acc, nid, did, ac = struct.unpack('>HHHH', rest[rpos:rpos+8])
        rpos += 8
        for _ in range(ac):
            alen = struct.unpack('>I', rest[rpos+2:rpos+6])[0]
            code_len = struct.unpack('>I', rest[rpos+10:rpos+14])[0]

            # 1. Patch longStart (code_len == 52)
            if code_len == 52 and rest[rpos+14] == 0x2a and rest[rpos+15] == 0xb7:
                new_code = bytearray([
                    0x2a,                                                 # aload_0
                    0x01,                                                 # aconst_null
                    0xb7, 0x00, 0x38,                                     # invokespecial displayErrorMessage(#56)
                    0x2a,                                                 # aload_0
                    0x13, (idx_cmd_str >> 8) & 0xff, idx_cmd_str & 0xff, # ldc_w cmd
                    0x13, (idx_dir_str >> 8) & 0xff, idx_dir_str & 0xff, # ldc_w dir
                    0x04,                                                 # iconst_1 (background=true)
                    0xb7, 0x00, 0xf2,                                     # invokespecial execute(#242)
                    0x57,                                                 # pop
                    0xb1                                                  # return
                ])
                while len(new_code) < 52:
                    new_code.append(0xb1)
                rest[rpos+14:rpos+14+52] = new_code

            # 2. Patch displayErrorMessage (code_len == 114)
            if code_len == 114 and rest[rpos+14] == 0x2a and rest[rpos+15] == 0xb4:
                code_display = bytearray([
                    0x2a, 0xb4, 0x00, 0x35,                               # aload_0, getfield context (#53)
                    0xb9, 0x00, 0x57, 0x01, 0x00,                         # invokeinterface getRootContainer (#87)
                    0x4d,                                                 # astore_2 (container)
                    0x2c,                                                 # aload_2
                    0xb6, 0x00, 0x59,                                     # invokevirtual removeAll (#89)
                    0x2c,                                                 # aload_2
                    0xbb, 0x00, 0x9c,                                     # new GridBagLayout (#156)
                    0x59,                                                 # dup
                    0xb7, 0x00, 0x9d,                                     # invokespecial GridBagLayout.<init> (#157)
                    0xb6, 0x00, 0x78,                                     # invokevirtual setLayout (#120)
                    0xbb, 0x00, 0x9e,                                     # new GridBagConstraints (#158)
                    0x59,                                                 # dup
                    0xb7, 0x00, 0x9f,                                     # invokespecial GridBagConstraints.<init> (#159)
                    0x3a, 0x04,                                           # astore 4 (gbc)
                    0x19, 0x04,                                           # aload 4
                    0x03,                                                 # iconst_0
                    0xb5, 0x00, 0xa0,                                     # putfield gridx (#160)
                    0x19, 0x04,                                           # aload 4
                    0x05,                                                 # iconst_2 (HORIZONTAL)
                    0xb5, 0x00, 0xa1,                                     # putfield fill (#161)
                    0x19, 0x04,                                           # aload 4
                    0x0f,                                                 # dconst_1
                    0xb5, 0x00, 0xa2,                                     # putfield weightx (#162)

                    # Label 1: Title
                    0x2c,                                                 # aload_2
                    0xb8, 0x00, 0x28,                                     # invokestatic getUI (#40)
                    0x13, (idx_msg1_str >> 8) & 0xff, idx_msg1_str & 0xff,# ldc_w msg1
                    0xb6, 0x00, 0x6f,                                     # invokevirtual newLabel (#111)
                    0x19, 0x04,                                           # aload 4
                    0xb6, 0x00, 0x7b,                                     # invokevirtual add (#123)

                    # Label 2: Timeout
                    0x2c,                                                 # aload_2
                    0xb8, 0x00, 0x28,                                     # invokestatic getUI (#40)
                    0x13, (idx_msg2_str >> 8) & 0xff, idx_msg2_str & 0xff,# ldc_w msg2
                    0xb6, 0x00, 0x6f,                                     # invokevirtual newLabel (#111)
                    0x19, 0x04,                                           # aload 4
                    0xb6, 0x00, 0x7b,                                     # invokevirtual add (#123)

                    # Label 3: Exit instruction
                    0x2c,                                                 # aload_2
                    0xb8, 0x00, 0x28,                                     # invokestatic getUI (#40)
                    0x13, (idx_msg3_str >> 8) & 0xff, idx_msg3_str & 0xff,# ldc_w msg3
                    0xb6, 0x00, 0x6f,                                     # invokevirtual newLabel (#111)
                    0x19, 0x04,                                           # aload 4
                    0xb6, 0x00, 0x7b,                                     # invokevirtual add (#123)

                    0xb1                                                  # return
                ])
                while len(code_display) < 114:
                    code_display.append(0xb1)
                rest[rpos+14:rpos+14+114] = code_display

            rpos += 6 + alen

    data_new.extend(rest)
    return bytes(data_new)


def wrap_line(s):
    """
    Wrap line according to JAR Manifest specification (RFC 2822 style).
    Lines must not exceed 72 bytes including CRLF (max 70 payload bytes).
    Continuation lines start with a leading space (max 69 payload bytes).
    Multi-byte UTF-8 character sequences are never split across line boundaries.
    """
    b = s.encode('utf-8') if isinstance(s, str) else s
    if len(b) <= 70:
        return b + b'\r\n'

    def safe_split(chunk, max_len):
        if len(chunk) <= max_len:
            return chunk, b''
        idx = max_len
        # Backtrack if idx points into the middle of a multi-byte UTF-8 sequence (0x80..0xBF)
        while idx > 0 and (chunk[idx] & 0xC0) == 0x80:
            idx -= 1
        if idx == 0:
            idx = max_len
        return chunk[:idx], chunk[idx:]

    out = bytearray()
    first, rem = safe_split(b, 70)
    out.extend(first + b'\r\n')
    while rem:
        chunk, rem = safe_split(rem, 69)
        out.extend(b' ' + chunk + b'\r\n')
    return bytes(out)


def build_launcher(template_path, keys_dir, out_path, app_name, cmd, work_dir,
                   vendor="Custom", title=None, timeout_msg=None, exit_msg=None, cover_path=None):
    if title is None:
        title = f"{app_name} Launcher"
    if timeout_msg is None:
        timeout_msg = "If you see this screen > 10s: press [BACK] to exit."
    if exit_msg is None:
        exit_msg = f"On {app_name} exit: press [BACK] twice if frozen."

    # Validate string lengths against JVM constant pool limits (max 65535 bytes)
    for label, val in [("cmd", cmd), ("work_dir", work_dir), ("title", title),
                       ("timeout_msg", timeout_msg), ("exit_msg", exit_msg)]:
        b_len = len(val.encode('utf-8'))
        if b_len > 65535:
            raise ValueError(f"Argument '{label}' exceeds maximum JVM Constant Pool length ({b_len} bytes > 65535)")

    if not os.path.isfile(template_path):
        raise FileNotFoundError(f"Template base.azw2 not found at: {template_path}")

    for alias in ['dntest', 'ditest', 'dktest']:
        p12_file = os.path.join(keys_dir, f'{alias}.p12')
        if not os.path.isfile(p12_file):
            raise FileNotFoundError(f"Developer certificate '{alias}.p12' not found in: {keys_dir}")

    src_zip = zipfile.ZipFile(template_path, 'r')
    files = {}
    for item in src_zip.infolist():
        if item.filename.startswith('META-INF/') or item.is_dir() or item.filename.endswith('/'):
            continue
        data = src_zip.read(item.filename)
        if item.filename == 'com/mobileread/ixtab/kindlelauncher/KualKindlet.class':
            data = patch_kindlet_class(data, cmd, work_dir, title, timeout_msg, exit_msg)
        elif item.filename == 'KindleLauncher.jpg' and cover_path and os.path.isfile(cover_path):
            with open(cover_path, 'rb') as cf:
                data = cf.read()
        files[item.filename] = data

    main_attrs = [
        "Manifest-Version: 1.0",
        "SDK-Specification-Version: 1.0",
        f"Implementation-Title: {app_name}",
        "Implementation-Version: 1.0",
        "Amazon-Cover-Image: KindleLauncher.jpg",
        "Extension-List: SDK",
        f"Implementation-Vendor: {vendor}",
        "Main-Class: com.mobileread.ixtab.kindlelauncher.KualKindlet",
        "Toolbar-Mode: persistent",
        "Font-Size-Mode: point",
        "SDK-Extension-Name: com.amazon.kindle.kindlet"
    ]

    mf_buf = bytearray()
    for attr in main_attrs:
        mf_buf.extend(wrap_line(attr))
    mf_buf.extend(b'\r\n')
    main_attrs_bytes = bytes(mf_buf)

    sorted_filenames = sorted(files.keys())
    section_map = {}

    for fn in sorted_filenames:
        data = files[fn]
        f_hash = base64.b64encode(hashlib.sha256(data).digest()).decode('ascii')
        sec = bytearray()
        sec.extend(wrap_line(f"Name: {fn}"))
        sec.extend(wrap_line(f"SHA-256-Digest: {f_hash}"))
        sec.extend(b'\r\n')
        sec_bytes = bytes(sec)
        section_map[fn] = sec_bytes
        mf_buf.extend(sec_bytes)

    manifest_bytes = bytes(mf_buf)
    main_attrs_sha = base64.b64encode(hashlib.sha256(main_attrs_bytes).digest()).decode('ascii')
    manifest_sha = base64.b64encode(hashlib.sha256(manifest_bytes).digest()).decode('ascii')

    sf_buf = bytearray()
    sf_buf.extend(wrap_line("Signature-Version: 1.0"))
    sf_buf.extend(wrap_line(f"SHA-256-Digest-Manifest-Main-Attributes: {main_attrs_sha}"))
    sf_buf.extend(wrap_line(f"SHA-256-Digest-Manifest: {manifest_sha}"))
    sf_buf.extend(wrap_line("Created-By: 1.8.0_442 (Temurin)"))
    sf_buf.extend(b'\r\n')

    for fn in sorted_filenames:
        sec_bytes = section_map[fn]
        sec_sha = base64.b64encode(hashlib.sha256(sec_bytes).digest()).decode('ascii')
        sf_buf.extend(wrap_line(f"Name: {fn}"))
        sf_buf.extend(wrap_line(f"SHA-256-Digest: {sec_sha}"))
        sf_buf.extend(b'\r\n')

    sf_bytes = bytes(sf_buf)

    signatures = {}
    for alias in ['dntest', 'ditest', 'dktest']:
        p12_file = os.path.join(keys_dir, f'{alias}.p12')
        with open(p12_file, 'rb') as f:
            key, cert, _ = pkcs12.load_key_and_certificates(f.read(), b'password')

        orig_rsa = src_zip.read(f'META-INF/{alias.upper()}.RSA')
        content, _ = decoder.decode(orig_rsa, asn1Spec=rfc2315.ContentInfo())
        sd, _ = decoder.decode(content['content'], asn1Spec=rfc2315.SignedData())

        sig = key.sign(sf_bytes, padding.PKCS1v15(), hashes.SHA256())
        sd['signerInfos'][0]['encryptedDigest'] = rfc2315.EncryptedDigest(sig)
        content['content'] = encoder.encode(sd)
        signatures[alias] = encoder.encode(content)

    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with zipfile.ZipFile(out_path, 'w', compression=zipfile.ZIP_DEFLATED) as out_zip:
        out_zip.writestr('META-INF/MANIFEST.MF', manifest_bytes)
        out_zip.writestr('META-INF/DNTEST.SF', sf_bytes)
        out_zip.writestr('META-INF/DNTEST.RSA', signatures['dntest'])
        out_zip.writestr('META-INF/DITEST.SF', sf_bytes)
        out_zip.writestr('META-INF/DITEST.RSA', signatures['ditest'])
        out_zip.writestr('META-INF/DKTEST.SF', sf_bytes)
        out_zip.writestr('META-INF/DKTEST.RSA', signatures['dktest'])

        for fn in sorted_filenames:
            out_zip.writestr(fn, files[fn])

    print(f"Successfully generated signed Kindle launcher: {out_path}")
    return out_path


def upload_to_kindle(local_path, kindle_ip, password, port=22):
    try:
        import paramiko
    except ImportError:
        print("Error: 'paramiko' is required for SSH upload. Run: pip install paramiko", file=sys.stderr)
        return False

    import socket
    print(f"Connecting to Kindle at {kindle_ip}:{port} via SSH (user: root)...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(
            kindle_ip,
            port=port,
            username='root',
            password=password,
            timeout=10,
            allow_agent=False,
            look_for_keys=False
        )
    except paramiko.AuthenticationException:
        print(f"Error: SSH authentication failed for root@{kindle_ip}. Check your --ssh-pass.", file=sys.stderr)
        print("Tip: Generate your Kindle root password from your serial number at: https://www.sven.de/kindle/", file=sys.stderr)
        return False
    except (socket.timeout, TimeoutError):
        print(f"Error: Connection to {kindle_ip}:{port} timed out. Ensure Kindle Wi-Fi / USBNetwork is on and awake.", file=sys.stderr)
        return False
    except (paramiko.SSHException, OSError) as e:
        print(f"Error: Could not connect to Kindle at {kindle_ip}:{port}: {e}", file=sys.stderr)
        return False

    try:
        filename = os.path.basename(local_path)
        remote_path = f"/mnt/us/documents/{filename}"

        sftp = client.open_sftp()
        print(f"Uploading {filename} -> {remote_path}...")
        sftp.put(local_path, remote_path)
        sftp.close()

        stdin, stdout, stderr = client.exec_command(f"ls -lh '{remote_path}'")
        output = stdout.read().decode('utf-8', errors='replace').strip()
        print(f"Remote file: {output}")
        print("Upload complete!")
        return True
    except Exception as e:
        print(f"Error during file transfer: {e}", file=sys.stderr)
        return False
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(
        description="Build signed .azw2 launcher document for Kindle 4 (K4NT / KDK 1.0)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # KOReader Launcher
  python make_launcher.py --name "KOReader" --cmd "/mnt/us/koreader/koreader.sh"

  # USBNetwork Switcher
  python make_launcher.py --name "Toggle USBNet" --cmd "/mnt/us/extensions/usbnet/bin/usbnet.sh toggle_usbnet"

  # Deploy to Kindle over Wi-Fi
  python make_launcher.py --name "KOReader" --cmd "/mnt/us/koreader/koreader.sh" --upload 192.168.1.23 --ssh-pass "YOUR_ROOT_PASS"
"""
    )
    parser.add_argument("-n", "--name", help="App name displayed in Kindle Home / Library")
    parser.add_argument("-c", "--cmd", help="Linux shell command or script path to execute")
    parser.add_argument("-d", "--dir", default=None, help="Working directory (default: /mnt/us)")
    parser.add_argument("-v", "--vendor", default=None, help="Implementation vendor string (default: Custom)")
    parser.add_argument("--title", help="Header text shown on launcher screen")
    parser.add_argument("--timeout-msg", help="Startup / timeout instruction note")
    parser.add_argument("--exit-msg", help="Exit return instruction note")
    parser.add_argument("--cover", help="Path to custom cover image (.jpg)")
    parser.add_argument("-o", "--output", help="Output .azw2 file path")
    parser.add_argument("--config", help="Path to JSON configuration file")
    parser.add_argument("--upload", help="Kindle IP address to automatically upload via SSH")
    parser.add_argument("--ssh-pass", default=None, help="Kindle SSH root password (generate at https://www.sven.de/kindle/)")

    args = parser.parse_args()

    # Load from config if provided
    config = {}
    if args.config:
        if not os.path.isfile(args.config):
            sys.exit(f"Error: Configuration file '{args.config}' not found.")
        try:
            with open(args.config, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            sys.exit(f"Error: Invalid JSON in configuration file '{args.config}': {e}")
        except Exception as e:
            sys.exit(f"Error reading configuration file '{args.config}': {e}")

    name = args.name or config.get("name")
    cmd = args.cmd or config.get("command")
    work_dir = args.dir or config.get("workdir") or "/mnt/us"
    vendor = args.vendor or config.get("vendor") or "Custom"
    title = args.title or config.get("title")
    timeout_msg = args.timeout_msg or config.get("timeout_msg")
    exit_msg = args.exit_msg or config.get("exit_msg")
    cover = args.cover or config.get("cover_image")

    # Validate required arguments
    if not name or not str(name).strip():
        sys.exit("Error: Missing required argument: --name (or 'name' in --config).\nRun with -h or --help for usage.")
    if not cmd or not str(cmd).strip():
        sys.exit("Error: Missing required argument: --cmd (or 'command' in --config).\nRun with -h or --help for usage.")

    # Sanitize manifest headers (no newlines/CR allowed)
    name = str(name).replace('\r', ' ').replace('\n', ' ').strip()
    vendor = str(vendor).replace('\r', ' ').replace('\n', ' ').strip()

    # Reject null bytes in parameters
    for label, val in [("name", name), ("cmd", cmd), ("dir", work_dir), ("vendor", vendor)]:
        if '\x00' in val:
            sys.exit(f"Error: Argument '{label}' cannot contain null bytes.")

    output = args.output or config.get("output") or f"{name}.azw2"

    if cover and not os.path.isfile(cover):
        sys.exit(f"Error: Specified cover image '{cover}' not found.")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    keys_dir = os.path.join(script_dir, "keys")
    template_path = os.path.join(script_dir, "template", "base.azw2")

    try:
        out_file = build_launcher(
            template_path=template_path,
            keys_dir=keys_dir,
            out_path=output,
            app_name=name,
            cmd=cmd,
            work_dir=work_dir,
            vendor=vendor,
            title=title,
            timeout_msg=timeout_msg,
            exit_msg=exit_msg,
            cover_path=cover
        )
    except FileNotFoundError as e:
        sys.exit(f"Error: {e}")
    except ValueError as e:
        sys.exit(f"Error: {e}")
    except OSError as e:
        sys.exit(f"Error creating output file '{output}': {e}")
    except Exception as e:
        sys.exit(f"Unexpected error while building launcher: {e}")

    if args.upload:
        ssh_pass = args.ssh_pass or config.get("ssh_pass")
        if not ssh_pass:
            if sys.stdin.isatty():
                import getpass
                print("Kindle root password is required for SSH upload.")
                print("Tip: Generate it from your serial number at: https://www.sven.de/kindle/")
                ssh_pass = getpass.getpass("Enter Kindle root password: ")
            if not ssh_pass:
                sys.exit("Error: --ssh-pass is required for SSH upload.\n"
                         "Generate your Kindle root password from your serial number at: https://www.sven.de/kindle/")
        success = upload_to_kindle(out_file, args.upload, password=ssh_pass, port=22)
        if not success:
            sys.exit(1)


if __name__ == '__main__':
    main()
