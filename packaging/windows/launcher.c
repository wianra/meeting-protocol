/* Meeting Protocol.exe: runs the bundled Python in-process (a GUI program, so no console
 * window). Sits in the Python folder next to python312.dll.
 *
 * Without arguments it starts the app. With arguments it behaves like `python`, which is
 * how the app starts its own workers (sys.executable). Wide-character APIs throughout, so
 * user names and recordings with umlauts work.
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <Python.h>
#include <stdlib.h>
#include <wchar.h>

#define LONG_PATH 32768

static wchar_t dir[LONG_PATH], value[LONG_PATH];

static void set(const wchar_t *name, const wchar_t *text) { _wputenv_s(name, text); }

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR command, int show) {
    (void)instance; (void)previous; (void)command; (void)show;
    DWORD n = GetModuleFileNameW(NULL, dir, LONG_PATH);
    if (n == 0 || n >= LONG_PATH) return 1;
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (slash == NULL) return 1;
    *slash = L'\0';

    set(L"PYTHONHOME", dir);
    set(L"PYTHONNOUSERSITE", L"1");
    set(L"PYTHONDONTWRITEBYTECODE", L"1");
    set(L"PYTHONUTF8", L"1"); /* Windows otherwise reads and writes text as cp1252 */
    const wchar_t *path = _wgetenv(L"PATH");
    swprintf(value, LONG_PATH, L"%ls\\bin;%ls", dir, path ? path : L"");
    set(L"PATH", value);
    swprintf(value, LONG_PATH, L"%ls\\models", dir);
    set(L"MEETING_PROTOCOL_BUNDLED_MODELS", value);
    if (_wgetenv(L"DIARIZE_HOME") == NULL && _wgetenv(L"LOCALAPPDATA") != NULL) {
        swprintf(value, LONG_PATH, L"%ls\\Meeting Protocol", _wgetenv(L"LOCALAPPDATA"));
        set(L"DIARIZE_HOME", value);
    }

    if (__argc < 2) {
        wchar_t *app[] = {__wargv[0], L"-m", L"meeting_protocol.cli", L"app", NULL};
        return Py_Main(4, app);
    }
    return Py_Main(__argc, __wargv);
}
