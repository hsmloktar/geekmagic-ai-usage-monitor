/* Keep the native app identity while running the checkout's Python environment.
 * The installer supplies paths and arguments in a generated configuration header. */
#include <dlfcn.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

static int fail(const char *reason) {
    fprintf(stderr, "GeekMagic startup failed: %s\n", reason);
    char *arguments[] = {
        "/usr/bin/osascript", "-e",
        "display alert \"GeekMagic AI Monitor\" message "
        "\"앱을 시작하지 못했습니다. 프로젝트에서 uv sync --locked 후 "
        "macos/install-app.sh를 다시 실행하세요.\"",
        NULL
    };
    pid_t child;
    if (posix_spawn(&child, arguments[0], NULL, NULL, arguments, environ) == 0)
        waitpid(child, NULL, 0);
    return 1;
}

int main(void) {
    if (chdir(PROJECT_ROOT) != 0)
        return fail("Project directory is missing.");
    mkdir("artifacts", 0755);
    mkdir("artifacts/logs", 0755);
    if (!freopen("artifacts/logs/launcher.log", "a", stderr))
        return fail("Cannot open launcher.log.");
    if (!freopen("artifacts/logs/launcher.log", "a", stdout))
        return fail("Cannot open launcher.log.");
    fprintf(stderr, "GeekMagic native launcher v3 starting.\n");
    fflush(stderr);
    setenv("PATH", PROVIDER_PATH, 1);
    void *library = dlopen(PYTHON_LIBRARY, RTLD_NOW | RTLD_GLOBAL);
    if (!library)
        return fail(dlerror());
    int (*python_main)(int, char **) = dlsym(library, "Py_BytesMain");
    if (!python_main)
        return fail(dlerror());
    char *arguments[] = PYTHON_ARGUMENTS;
    return python_main((int)(sizeof(arguments) / sizeof(arguments[0])) - 1, arguments);
}
