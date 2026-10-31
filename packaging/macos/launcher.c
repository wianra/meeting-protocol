/* The app's main executable: runs the bundled Python in-process, so macOS shows
 * "Meeting Protocol" and its icon instead of Python.
 *
 * Without arguments it starts the app. With arguments it behaves like `python`, which is
 * how the app starts its own workers and the network-sandboxed window (sys.executable).
 */
#include <Python.h>
#include <libgen.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv) {
    char exe[PATH_MAX], real[PATH_MAX], res[PATH_MAX], value[PATH_MAX * 2];
    uint32_t size = sizeof exe;
    if (_NSGetExecutablePath(exe, &size) != 0 || realpath(exe, real) == NULL) {
        fprintf(stderr, "Meeting Protocol: cannot locate itself\n");
        return 1;
    }
    snprintf(value, sizeof value, "%s/../Resources", dirname(real));
    if (realpath(value, res) == NULL) {
        fprintf(stderr, "Meeting Protocol: missing Resources folder\n");
        return 1;
    }
    snprintf(value, sizeof value, "%s/python", res);
    setenv("PYTHONHOME", value, 1);
    setenv("PYTHONNOUSERSITE", "1", 1);
    setenv("PYTHONDONTWRITEBYTECODE", "1", 1);
    snprintf(value, sizeof value, "%s/bin:/usr/bin:/bin:/usr/sbin:/sbin", res);
    setenv("PATH", value, 1);
    snprintf(value, sizeof value, "%s/models", res);
    setenv("MEETING_PROTOCOL_BUNDLED_MODELS", value, 1);
    if (getenv("DIARIZE_HOME") == NULL && getenv("HOME") != NULL) {
        snprintf(value, sizeof value, "%s/Library/Application Support/Meeting Protocol",
                 getenv("HOME"));
        setenv("DIARIZE_HOME", value, 1);
    }
    /* Older macOS versions pass a -psn_ process serial number when opened from Finder. */
    if (argc < 2 || strncmp(argv[1], "-psn", 4) == 0) {
        char *app[] = {argv[0], "-m", "meeting_protocol.cli", "app", NULL};
        return Py_BytesMain(4, app);
    }
    return Py_BytesMain(argc, argv);
}
