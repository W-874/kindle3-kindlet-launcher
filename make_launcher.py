#!/usr/bin/env python3
"""
Standalone Kindlet launcher builder for Kindle 3 and other KDK 1.0 devices.
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


KUAL_CLASS = 'com/mobileread/ixtab/kindlelauncher/KualKindlet'
KUAL_CLASS_FILE = KUAL_CLASS + '.class'
SUICIDAL_KINDLET = 'ixtab/jailbreak/SuicidalKindlet'
UI_ADAPTER = 'com/mobileread/ixtab/kindlelauncher/ui/UIAdapter'
KINDLET_CONTEXT = 'com/amazon/kindle/kindlet/KindletContext'
AUTO_EXIT = 'com/mobileread/ixtab/kindlelauncher/AutoExit'

CP_FIELDREF, CP_METHODREF, CP_INTERFACE_METHODREF = 9, 10, 11


def _read(data, pos, fmt):
    end = pos + struct.calcsize(fmt)
    if end > len(data):
        raise ValueError("KualKindlet.class is truncated")
    return struct.unpack(fmt, data[pos:end]) + (end,)


def _skip(data, pos, length):
    if pos + length > len(data):
        raise ValueError("KualKindlet.class is truncated")
    return pos + length


def _skip_attributes(data, pos):
    count, pos = _read(data, pos, '>H')
    for _ in range(count):
        _, length, pos = _read(data, pos, '>HI')
        pos = _skip(data, pos, length)
    return pos


def _parse_class(data):
    """Parse the whole class file; return constant pool, class names and method Code spans."""
    magic, _, _, cp_count, pos = _read(data, 0, '>IHHH')
    if magic != 0xCAFEBABE:
        raise ValueError("KualKindlet.class has an invalid class file magic")

    cp = [None] * cp_count
    i = 1
    while i < cp_count:
        tag, pos = _read(data, pos, '>B')
        if tag == 1:
            length, pos = _read(data, pos, '>H')
            end = _skip(data, pos, length)
            cp[i] = (tag, bytes(data[pos:end]))
            pos = end
        elif tag in (7, 8):
            value, pos = _read(data, pos, '>H')
            cp[i] = (tag, value)
        elif tag in (3, 4):
            pos = _skip(data, pos, 4)
        elif tag in (5, 6):
            pos = _skip(data, pos, 8)
            i += 1
        elif tag in (CP_FIELDREF, CP_METHODREF, CP_INTERFACE_METHODREF, 12):
            first, second, pos = _read(data, pos, '>HH')
            cp[i] = (tag, first, second)
        else:
            raise ValueError(f"KualKindlet.class has unsupported constant pool tag {tag}")
        i += 1
    cp_end = pos

    def entry(index, tag):
        if not 0 < index < cp_count or cp[index] is None or cp[index][0] != tag:
            raise ValueError(f"KualKindlet.class has an invalid constant pool reference #{index}")
        return cp[index]

    def utf8(index):
        return entry(index, 1)[1].decode('utf-8', errors='replace')

    def class_name(index):
        return utf8(entry(index, 7)[1])

    def ref(tag, owner, name, descriptor):
        matches = []
        for index, item in enumerate(cp):
            if item is None or item[0] != tag or class_name(item[1]) != owner:
                continue
            _, name_index, descriptor_index = entry(item[2], 12)
            if utf8(name_index) == name and utf8(descriptor_index) == descriptor:
                matches.append(index)
        if len(matches) != 1:
            raise ValueError(f"KualKindlet.class must reference {owner}.{name}{descriptor} exactly once")
        return matches[0]

    def class_ref(name):
        matches = [index for index, item in enumerate(cp)
                   if item is not None and item[0] == 7 and utf8(item[1]) == name]
        if len(matches) != 1:
            raise ValueError(f"KualKindlet.class must reference class {name} exactly once")
        return matches[0]

    _, this_class, super_class, interface_count, pos = _read(data, pos, '>HHHH')
    pos = _skip(data, pos, interface_count * 2)

    field_count, pos = _read(data, pos, '>H')
    for _ in range(field_count):
        pos = _skip_attributes(data, _skip(data, pos, 6))

    methods = {}
    method_count, pos = _read(data, pos, '>H')
    for _ in range(method_count):
        _, name_index, descriptor_index, attribute_count, pos = _read(data, pos, '>HHHH')
        key = (utf8(name_index), utf8(descriptor_index))
        code_attributes = []
        for _ in range(attribute_count):
            start = pos
            attribute_name, length, pos = _read(data, pos, '>HI')
            end = _skip(data, pos, length)
            if utf8(attribute_name) == 'Code':
                max_stack, max_locals, code_length, code_pos = _read(data, pos, '>HHI')
                code_end = _skip(data, code_pos, code_length)
                exception_count, after = _read(data, code_end, '>H')
                if _skip_attributes(data, _skip(data, after, exception_count * 8)) != end:
                    raise ValueError(f"KualKindlet.class has a malformed Code attribute in {key[0]}")
                code_attributes.append({
                    'start': start, 'end': end, 'name_index': attribute_name,
                    'code': bytes(data[code_pos:code_end]),
                    'exceptions': bytes(data[code_end + 2:after + exception_count * 8]),
                    'max_stack': max_stack, 'max_locals': max_locals,
                })
            pos = end
        methods.setdefault(key, []).append(code_attributes)

    pos = _skip_attributes(data, pos)
    if pos != len(data):
        raise ValueError("KualKindlet.class has trailing bytes after the class attributes")

    def method_code(name, descriptor):
        found = methods.get((name, descriptor), [])
        if len(found) != 1 or len(found[0]) != 1:
            raise ValueError(f"KualKindlet.class must define {name}{descriptor} once with one Code attribute")
        return found[0][0]

    return {
        'cp_count': cp_count, 'cp_end': cp_end, 'ref': ref, 'class_ref': class_ref,
        'method_code': method_code,
        'this': class_name(this_class), 'super': class_name(super_class),
    }


def _u2(value):
    return struct.pack('>H', value)


def _code_attribute(name_index, max_stack, max_locals, code, exceptions=b''):
    """Rebuild Code, preserving supplied handlers but dropping stale code-offset metadata."""
    body = (struct.pack('>HHI', max_stack, max_locals, len(code)) + code
            + _u2(len(exceptions) // 8) + exceptions + _u2(0))
    return struct.pack('>HI', name_index, len(body)) + body


def patch_kindlet_class(data, cmd, work_dir, title_msg, timeout_msg, exit_msg):
    """
    Patch the KUAL template so longStart shows a status screen, stores the command in
    commandToRunOnExit/dirToChangeToOnExit and asks the framework to close the Kindlet.
    The template's own onStop launches the command during the framework's stop transition.
    Raises ValueError for anything other than the unpatched KUAL template.
    """
    try:
        cls = _parse_class(data)
    except (struct.error, IndexError) as e:
        raise ValueError(f"KualKindlet.class is malformed: {e}") from None
    if cls['this'] != KUAL_CLASS or cls['super'] != SUICIDAL_KINDLET:
        raise ValueError(f"Template main class must be {KUAL_CLASS} extending {SUICIDAL_KINDLET}")

    ref = cls['ref']
    command_field = ref(CP_FIELDREF, KUAL_CLASS, 'commandToRunOnExit', 'Ljava/lang/String;')
    dir_field = ref(CP_FIELDREF, KUAL_CLASS, 'dirToChangeToOnExit', 'Ljava/lang/String;')
    context_field = ref(CP_FIELDREF, KUAL_CLASS, 'context', f'L{KINDLET_CONTEXT};')
    status_field = ref(CP_FIELDREF, KUAL_CLASS, 'status', 'Ljava/awt/Component;')
    get_ui = ref(CP_METHODREF, KUAL_CLASS, 'getUI', f'()L{UI_ADAPTER};')
    new_button = ref(CP_METHODREF, UI_ADAPTER, 'newButton',
                     '(Ljava/lang/String;Ljava/awt/event/ActionListener;Ljava/awt/event/KeyListener;'
                     'Lcom/mobileread/ixtab/kindlelauncher/resources/KualEntry;)Ljava/awt/Component;')
    display_error = ref(CP_METHODREF, KUAL_CLASS, 'displayErrorMessage', '(Ljava/lang/String;)V')
    initialize_state = ref(CP_METHODREF, KUAL_CLASS, 'initializeState', '()V')
    execute = ref(CP_METHODREF, KUAL_CLASS, 'execute', '(Ljava/lang/String;Ljava/lang/String;Z)Ljava/lang/Process;')
    get_root = ref(CP_INTERFACE_METHODREF, KINDLET_CONTEXT, 'getRootContainer', '()Ljava/awt/Container;')
    remove_all = ref(CP_METHODREF, 'java/awt/Container', 'removeAll', '()V')
    set_layout = ref(CP_METHODREF, 'java/awt/Container', 'setLayout', '(Ljava/awt/LayoutManager;)V')
    add = ref(CP_METHODREF, 'java/awt/Container', 'add', '(Ljava/awt/Component;Ljava/lang/Object;)V')
    new_label = ref(CP_METHODREF, UI_ADAPTER, 'newLabel', '(Ljava/lang/String;)Ljava/awt/Component;')
    gbl_init = ref(CP_METHODREF, 'java/awt/GridBagLayout', '<init>', '()V')
    gbc_init = ref(CP_METHODREF, 'java/awt/GridBagConstraints', '<init>', '()V')
    gridx = ref(CP_FIELDREF, 'java/awt/GridBagConstraints', 'gridx', 'I')
    fill = ref(CP_FIELDREF, 'java/awt/GridBagConstraints', 'fill', 'I')
    weightx = ref(CP_FIELDREF, 'java/awt/GridBagConstraints', 'weightx', 'D')
    gbl_class = cls['class_ref']('java/awt/GridBagLayout')
    gbc_class = cls['class_ref']('java/awt/GridBagConstraints')

    long_start = cls['method_code']('longStart', '()V')
    display = cls['method_code']('displayErrorMessage', '(Ljava/lang/String;)V')
    on_stop = cls['method_code']('onStop', '()V')
    if not long_start['code'].startswith(b'\x2a\xb7' + _u2(initialize_state)):
        raise ValueError("KualKindlet.longStart is not the original KUAL body (template already patched or unsupported)")
    if (b'\xb4' + _u2(command_field) not in on_stop['code']
            or b'\xb7' + _u2(execute) not in on_stop['code']):
        raise ValueError("KualKindlet.onStop does not run commandToRunOnExit; unsupported template")

    cp_count = cls['cp_count']
    # Ten string entries plus symbolic AutoExit class / arm / cancel references.
    if cp_count + 20 > 0xFFFF:
        raise ValueError("KualKindlet.class constant pool is full")
    new_cp_entries = bytearray()
    string_indices = []
    for offset, value in enumerate((cmd, work_dir, title_msg, timeout_msg, exit_msg)):
        raw = value.encode('utf-8')
        utf8_index = cp_count + offset * 2
        new_cp_entries += b'\x01' + _u2(len(raw)) + raw + b'\x08' + _u2(utf8_index)
        string_indices.append(utf8_index + 1)
    cmd_str, dir_str, title_str, timeout_str, exit_str = string_indices

    def utf8_entry(value):
        raw = value.encode('utf-8')
        return b'\x01' + _u2(len(raw)) + raw

    helper_class = cp_count + 11
    arm_method = cp_count + 15
    cancel_method = cp_count + 19
    new_cp_entries += (
        utf8_entry(AUTO_EXIT) + b'\x07' + _u2(cp_count + 10)
        + utf8_entry('arm') + utf8_entry(f'(L{KINDLET_CONTEXT};Ljava/awt/Component;)V')
        + b'\x0c' + _u2(cp_count + 12) + _u2(cp_count + 13)
        + b'\x0a' + _u2(helper_class) + _u2(cp_count + 14)
        + utf8_entry('cancel') + utf8_entry('(Ljava/awt/Component;)V')
        + b'\x0c' + _u2(cp_count + 16) + _u2(cp_count + 17)
        + b'\x0a' + _u2(helper_class) + _u2(cp_count + 18)
    )

    # longStart (runs on the AWT event thread via KualKindlet$2 -> access$600):
    #   displayErrorMessage(null); commandToRunOnExit = cmd; dirToChangeToOnExit = dir;
    #   AutoExit.arm(context, status); // waits for real shown/focus events, not a delay
    long_start_code = (
        b'\x2a\x01\xb7' + _u2(display_error) +                     # aload_0, aconst_null, invokespecial
        b'\x2a\x13' + _u2(cmd_str) + b'\xb5' + _u2(command_field) +  # aload_0, ldc_w cmd, putfield
        b'\x2a\x13' + _u2(dir_str) + b'\xb5' + _u2(dir_field) +      # aload_0, ldc_w dir, putfield
        b'\x2a\xb4' + _u2(context_field) +                           # context
        b'\x2a\xb4' + _u2(status_field) +                            # focus target
        b'\xb8' + _u2(arm_method) +                                  # AutoExit.arm
        b'\xb1'                                                      # return
    )

    # displayErrorMessage(String): locals 0=this, 1=ignored arg, 2=root container, 3=constraints.
    display_code = bytearray(
        b'\x2a\xb4' + _u2(context_field) +                           # aload_0, getfield context
        b'\xb9' + _u2(get_root) + b'\x01\x00' +                      # invokeinterface getRootContainer
        b'\x4d' +                                                    # astore_2
        b'\x2c\xb6' + _u2(remove_all) +                              # aload_2, removeAll
        b'\x2c\xbb' + _u2(gbl_class) + b'\x59\xb7' + _u2(gbl_init) + # aload_2, new/dup/<init> GridBagLayout
        b'\xb6' + _u2(set_layout) +                                  # setLayout
        b'\xbb' + _u2(gbc_class) + b'\x59\xb7' + _u2(gbc_init) +     # new/dup/<init> GridBagConstraints
        b'\x4e' +                                                    # astore_3
        b'\x2d\x03\xb5' + _u2(gridx) +                               # gbc.gridx = 0
        b'\x2d\x05\xb5' + _u2(fill) +                                # gbc.fill = HORIZONTAL
        b'\x2d\x0f\xb5' + _u2(weightx)                               # gbc.weightx = 1.0
    )
    # A real KUAL button can own focus; labels alone cannot establish input readiness.
    # No action/key listeners: the launcher has no initialized KUAL menu to navigate.
    display_code += (
        b'\x2a\xb8' + _u2(get_ui) + b'\x13' + _u2(title_str)
        + b'\x01\x01\x01\xb6' + _u2(new_button) + b'\xb5' + _u2(status_field)
        + b'\x2c\x2a\xb4' + _u2(status_field) + b'\x2d\xb6' + _u2(add)
    )
    for string_index in (timeout_str, exit_str):
        display_code += (
            b'\x2c\xb8' + _u2(get_ui) +                              # aload_2, invokestatic getUI
            b'\x13' + _u2(string_index) +                            # ldc_w message
            b'\xb6' + _u2(new_label) +                               # invokevirtual newLabel
            b'\x2d\xb6' + _u2(add)                                   # aload_3, invokevirtual add
        )
    display_code += b'\xb1'                                          # return

    # Cancel a queued automatic exit before manual Back/stop can tear down the window.
    # Relative branches in the unchanged body retain their offsets; handler PCs shift.
    stop_prefix = b'\x2a\xb4' + _u2(status_field) + b'\xb8' + _u2(cancel_method)
    stop_exceptions = bytearray()
    for start, end, handler, catch_type in struct.iter_unpack('>HHHH', on_stop['exceptions']):
        stop_exceptions += struct.pack('>HHHH', start + len(stop_prefix), end + len(stop_prefix),
                                       handler + len(stop_prefix), catch_type)

    replacements = sorted([
        (8, 10, _u2(cp_count + 20)),
        (cls['cp_end'], cls['cp_end'], bytes(new_cp_entries)),
        (long_start['start'], long_start['end'],
         _code_attribute(long_start['name_index'], 2, 1, long_start_code)),
        (display['start'], display['end'],
         _code_attribute(display['name_index'], 6, 4, bytes(display_code))),
        (on_stop['start'], on_stop['end'],
         _code_attribute(on_stop['name_index'], on_stop['max_stack'], on_stop['max_locals'],
                         stop_prefix + on_stop['code'], bytes(stop_exceptions))),
    ])
    out = bytearray()
    pos = 0
    for start, end, replacement in replacements:
        out += data[pos:start]
        out += replacement
        pos = end
    out += data[pos:]
    return bytes(out)


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
        timeout_msg = "Closing launcher before starting the application."
    if exit_msg is None:
        exit_msg = "The application should return to the Kindle Home screen on exit."

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
        if item.filename == KUAL_CLASS_FILE:
            data = patch_kindlet_class(data, cmd, work_dir, title, timeout_msg, exit_msg)
        elif item.filename == 'KindleLauncher.jpg' and cover_path and os.path.isfile(cover_path):
            with open(cover_path, 'rb') as cf:
                data = cf.read()
        files[item.filename] = data
    if KUAL_CLASS_FILE not in files:
        raise ValueError(f"Template does not contain the main class {KUAL_CLASS_FILE}")
    helper_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'template', 'AutoExit.class')
    with open(helper_path, 'rb') as helper:
        helper_data = helper.read()
    helper_class = _parse_class(helper_data)
    if helper_class['this'] != AUTO_EXIT or helper_data[4:8] != b'\x00\x00\x00\x30':
        raise ValueError("AutoExit.class must be the Java 1.4 launcher focus helper")
    files[AUTO_EXIT + '.class'] = helper_data

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
        description="Build a signed .azw2 launcher for Kindle 3 and other KDK 1.0 devices",
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
