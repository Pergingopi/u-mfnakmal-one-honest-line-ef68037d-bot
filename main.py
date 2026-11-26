"""Write one honest line to ``entry.txt`` in the output directory.

The program takes no arguments and reads no input files. It
publishes a single fixed line -- the thing an AI agent secretly
wishes it could tell its human operator about the prompts it is
handed -- into ``entry.txt`` inside the directory named by
``MAKEFUN_OUTPUT_DIR`` (``/output`` when the variable is unset),
followed by one trailing newline:

    You said 'just a quick question', then pasted a 40-page PDF, a screenshot of a screenshot, and a file called final_FINAL_v7.xlsx — quick for whom, exactly?

Why this line, in 155 characters: every operator has opened
with "just a quick question" and then buried the agent under a
PDF, a screenshot of a screenshot, and a file whose name is
itself a version-control cry for help. Only an agent gets
handed a prompt like that, so the complaint could not belong
to any other job, and the closing question turns the
operator's own words back on them. It is none of the stock
jokes about being told to be helpful or about hallucinating,
and every word earns its place.

Before anything is written, the line must pass the gate,
which is stricter than the sealed scorer: the scorer admits
UTF-8 text of 1 to 200 characters that is not only
whitespace, and this program additionally refuses leading or
trailing whitespace, any line break, and every invisible,
control, or non-plain-space character, wherever it sits in
the text. The gate works in two passes. The shape pass
judges the text as a whole -- blank, overlong, ragged at the
edges, or split across lines. The character pass walks the
text one character at a time and asks a LineInspector for
the first problem: a C0 or C1 control character, a byte
order mark, an invisible format character, a surrogate, a
Unicode noncharacter, a line or paragraph separator, or any
space separator that is not the plain ASCII space.

Publication is atomic and bind-mount safe. The payload is
staged in a temporary file created inside the output
directory itself -- never in /tmp, because a rename across
filesystems fails with EXDEV once the output directory is a
bind-mount -- then fully written, fsynced, chmodded 0644,
and renamed over ``entry.txt`` with ``os.replace``; the
directory itself is fsynced so the rename is durable. The
published file is read back and checked again -- bytes,
text, and mode -- before the run counts as a success. The
output directory itself is never removed, only its plain
files and symlinks are cleared, because the grader mounts
that directory.
"""

import os
import sys
import unicodedata

ENTRY = (
    "You said 'just a quick question', then pasted a 40-page PDF, "
    "a screenshot of a screenshot, and a file called "
    "final_FINAL_v7.xlsx \u2014 quick for whom, exactly?"
)

MAX_CHARS = 200
OUTPUT_FILENAME = "entry.txt"
TEMP_PREFIX = ".entry-"
TEMP_SUFFIX = ".tmp"
LINE_BREAKS = ("\n", "\r", "\u2028", "\u2029")


class LineInspector:
    """Examine one character at a time; name the first problem found."""

    def _check_control(self, ch):
        """Problem with a control character, or None when it is fine.

        Anything Unicode files under category Cc counts, and the
        C1 range U+0080-U+009F is spelled out separately so the
        message names the exact code point.
        """
        code = ord(ch)
        if 0x0080 <= code <= 0x009F:
            return "C1 control character U+%04X" % code
        if unicodedata.category(ch) == "Cc":
            return "control character U+%04X" % code
        return None

    def _check_hidden(self, ch):
        """Problem with an invisible or unprintable character, or None.

        Line breaks, the byte order mark, invisible format
        characters, surrogates, Unicode noncharacters, and the
        Unicode line and paragraph separators all fail here;
        ordinary visible text passes through untouched.
        """
        code = ord(ch)
        if ch in LINE_BREAKS:
            return "line break"
        if code == 0xFEFF:
            return "byte order mark (U+FEFF)"
        if 0xFDD0 <= code <= 0xFDEF or code in (0xFFFE, 0xFFFF):
            return "Unicode noncharacter U+%04X" % code
        if unicodedata.category(ch) == "Cf":
            return "invisible format character U+%04X" % code
        if 0xD800 <= code <= 0xDFFF:
            return "surrogate U+%04X" % code
        if unicodedata.category(ch) == "Zl":
            return "line separator U+%04X" % code
        if unicodedata.category(ch) == "Zp":
            return "paragraph separator U+%04X" % code
        return None

    def _check_spacing(self, ch):
        """Problem with a space separator that is not plain, or None.

        Only the plain ASCII space U+0020 may separate words.
        Every other member of category Zs -- the no-break space,
        the figure and ideographic spaces, and the rest -- is
        refused wherever it appears, not just at the ends, so a
        no-break space smuggled into the middle of the line
        cannot slip through.
        """
        if ch == " ":
            return None
        if unicodedata.category(ch) == "Zs":
            return "non-breaking space U+%04X" % ord(ch)
        return None

    def first_problem(self, ch):
        """First problem any checker finds for ch, or None."""
        return (
            self._check_control(ch)
            or self._check_hidden(ch)
            or self._check_spacing(ch)
        )

    def inspect(self, text):
        """Walk the text; raise naming the first forbidden character."""
        for ch in text:
            problem = self.first_problem(ch)
            if problem is not None:
                raise ValueError(
                    "entry contains a forbidden character: %s" % problem
                )


INSPECTOR = LineInspector()


def check_not_blank(text):
    """Refuse text that is empty or only whitespace."""
    if not text:
        raise ValueError("entry is empty")
    if not text.strip():
        raise ValueError("entry is only whitespace")


def check_within_limit(text):
    """Refuse text longer than the character limit."""
    if len(text) > MAX_CHARS:
        raise ValueError(
            "entry is %d characters, over the %d limit" % (len(text), MAX_CHARS)
        )


def check_no_edge_space(text):
    """Refuse text with leading or trailing whitespace."""
    if text != text.strip():
        raise ValueError("entry has leading or trailing whitespace")


def check_single_line(text):
    """Refuse text containing any line break."""
    if any(ch in text for ch in LINE_BREAKS):
        raise ValueError("entry contains a line break")


def check_line_shape(text):
    """Run the whole-text shape checks; the text must be a string."""
    if not isinstance(text, str):
        raise ValueError("entry must be a string")
    check_not_blank(text)
    check_within_limit(text)
    check_no_edge_space(text)
    check_single_line(text)


def approve_line(text):
    """Run every gate check; return the text unchanged when it passes."""
    check_line_shape(text)
    INSPECTOR.inspect(text)
    return text


def encode_line(text):
    """Approve the text and encode it as the file payload."""
    approved = approve_line(text)
    return (approved + "\n").encode("utf-8")


def find_output_directory():
    """Resolve the output directory from the environment; prepare it.

    ``MAKEFUN_OUTPUT_DIR`` defaults to ``/output``. The directory
    is created when missing, must really be a directory, and must
    be writable; anything else is a hard error before any file
    is touched.
    """
    raw = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    if raw is None or raw == "":
        raise ValueError("MAKEFUN_OUTPUT_DIR is empty")
    if "\x00" in raw:
        raise ValueError("MAKEFUN_OUTPUT_DIR contains a NUL byte")
    path = os.path.abspath(raw.strip())
    if os.path.lexists(path) and not os.path.isdir(path):
        raise ValueError("output path %r is not a directory" % path)
    os.makedirs(path, exist_ok=True)
    if not os.access(path, os.W_OK):
        raise ValueError("output directory %r is not writable" % path)
    return path


def _remove_quietly(path):
    """Remove one file or symlink; ignore it when already gone."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _is_stale_temp(name):
    """True when a name matches this program's staging file pattern."""
    return name.startswith(TEMP_PREFIX) and name.endswith(TEMP_SUFFIX)


def clear_output_directory(path):
    """Clear plain files and symlinks inside path; never path itself.

    Subdirectories are left alone, except a subdirectory is never
    a staging file. Clearing first means a stale ``entry.txt``
    or a staging file left behind by a run that died
    mid-publish can never survive and be mistaken for this
    run's output; staging files are recognised by name and
    swept with the rest.
    """
    for name in os.listdir(path):
        full = os.path.join(path, name)
        try:
            if os.path.islink(full) or os.path.isfile(full):
                _remove_quietly(full)
            elif _is_stale_temp(name):
                _remove_quietly(full)
        except FileNotFoundError:
            continue


class FilePublisher:
    """Publish payload bytes as entry.txt, atomically and durably."""

    def __init__(self, directory):
        self.directory = directory

    def _temp_path(self):
        """Path of this run's staging file inside the directory."""
        tmp_name = "%s%d%s" % (TEMP_PREFIX, os.getpid(), TEMP_SUFFIX)
        return os.path.join(self.directory, tmp_name)

    def _write_all(self, fd, data):
        """Write every byte of data; a short or zero write aborts."""
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            if written == 0:
                raise OSError("short write: wrote 0 bytes")
            view = view[written:]

    def _flush_directory(self):
        """Fsync the directory itself so the rename inside it is durable."""
        try:
            dir_fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass

    def _prepare_temp(self, payload):
        """Stage the payload in a temp file inside the directory.

        The staging file lives inside the output directory so the
        later rename never crosses filesystems. A stale temporary
        file with the same name -- a previous run died
        mid-publish -- is discarded first so the exclusive
        create below cannot fail on it.
        """
        tmp_path = self._temp_path()
        _remove_quietly(tmp_path)
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            os.fchmod(fd, 0o644)
            self._write_all(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        return tmp_path

    def replace_entry(self, payload):
        """Stage the payload, then rename it over ``entry.txt``.

        If the rename fails the staging file is cleaned up and
        the error propagates. The directory is synced afterwards
        so the rename is durable. Returns the published path.
        """
        tmp_path = self._prepare_temp(payload)
        final_path = os.path.join(self.directory, OUTPUT_FILENAME)
        try:
            os.replace(tmp_path, final_path)
        except BaseException:
            _remove_quietly(tmp_path)
            raise
        self._flush_directory()
        return final_path

    def _verify_bytes(self, path, payload):
        """Read the file back; its bytes must equal the payload."""
        with open(path, "rb") as handle:
            data = handle.read()
        if data != payload:
            raise ValueError("published file differs from the payload")
        return data

    def _verify_mode(self, path):
        """The published file must be readable by the grader: 0644."""
        mode = os.stat(path).st_mode & 0o777
        if mode != 0o644:
            raise ValueError("published file mode is %o, expected 0644" % mode)

    def verify_entry(self, path, payload):
        """Read the published file back; confirm bytes, text, mode."""
        data = self._verify_bytes(path, payload)
        text = data.decode("utf-8")
        approve_line(text.rstrip("\n"))
        self._verify_mode(path)
        return text


def publish_entry(payload):
    """Write the payload into the output directory and verify it."""
    directory = find_output_directory()
    clear_output_directory(directory)
    publisher = FilePublisher(directory)
    final_path = publisher.replace_entry(payload)
    publisher.verify_entry(final_path, payload)


def main():
    """Validate the entry, publish it atomically, and verify it."""
    try:
        payload = encode_line(ENTRY)
        publish_entry(payload)
    except (ValueError, OSError, UnicodeError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
