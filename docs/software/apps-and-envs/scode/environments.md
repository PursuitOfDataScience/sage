# Managing `scode` Environments

This guide covers everything you need to create, switch between, and manage `scode` environments. These are lightweight, isolated workspaces stored in `~/.scode/envs/`, containing your VS Code Server extensions, user data, and cached assets.

---

## 1  What *is* an `scode` environment?

An **`scode` environment** is a directory at `~/.scode/envs/<quality>/<name>/` that contains:

- an `extensions/` folder for VS Code Server extensions
- a `data/` folder for user settings and server logs

You can think of it as the VS Code equivalent of a Conda environment: create as many as you like, each with its own extensions and settings.

In the environment path:

- `<quality>` is either `stable` or `insiders` (currently, `scode` only support the `stable` version of VS Code).
- `<name>` is the name for the scode environment, when you run a scode command that require a working `scode` environment (e.g., `scode serve` or `scode ext`), a default environment with the name `default` will be **automatically created and activated**.

The `default` environment should be sufficient for most use cases. Custom environments, however, can help isolate extension sets. They are ideal for troubleshooting conflicts or separating projects by programming languages.

---

## 2  Creating your first `scode` environment

```bash
# Create an custom `scode` env and have it activated globally
scode create myenv
scode activate myenv

# Install extensions into the activated environment
scode ext install ms-python.python ms-toolsai.jupyter

# Launch VS Code Server using that env
scode serve-web -- --account <pi-account> --time 01:00:00
```

1. `scode create <env_name>` initializes a new environment under `~/.scode/envs/stable/<env_name>/`.
2. `scode activate <env_name>` sets it as the global default (persisted in `~/.scode/env-stable`).
3. `scode ext install …` installs the specified extensions to the activated environment.
4. `scode serve-web` will launch the server with the extensions and user settings from the activated environment.

---

## 3  Command reference

### 3.1  `scode create`

- **Usage:** `scode create <env_name>`
- **Purpose:** Create a fresh `scode` environment.
- **Behavior:**

    - Directory `~/.scode/envs/stable/<env_name>/` is created (quality defaults to *stable*).
    - No VS Code binaries are installed yet. That happens lazily on first `serve-web`.
    - Errors out if `<env_name>` already exists.

### 3.2  `scode activate`

- **Usage:** `scode activate <env_name>`
- **Purpose:** Activate and use an `scode` env globally.
- **Behavior:**

    - A plaintext file `~/.scode/env-<quality>` stores the environment  selection.
    - Subsequent `scode` commands inherit this env **unless** an explicit `--env` overrides it.

### 3.3  `scode list`

- **Usage:** `scode list`
- **Output example:**

    ```bash
    Local stable channel environments:
       myenv
    *  default
    ```

    An asterisk `*` indicates the currently active environment.

### 3.4  `scode remove`

- **Usage:** `scode remove <env_name>`
- **Purpose:** Removes an `scode` env with all associated extensions and user data
- **Behavior:**
    - Recursively deletes the env directory.
    - If an active environment is removed, the next available environment will be activated automatically.

---

## 4  Using environments with `serve-web`

Both of the following examples starts a VS Code server with the `myenv` `scode` environment.

1. **Inline**: pass `--env <name>` every time

    ```bash
    scode serve-web --env myenv -- --time 02:00:00 --account <pi-account>
    ```

2. **Activate**: permanently sets an environment as global default

    ```bash
    scode activate myenv
    scode serve-web -- --time 02:00:00 --account <pi-account>
    ```

!!! tip

    If you omit both `--env` *and* `activate`, `scode` falls back to the implicit **`default`** environment (created and activated on first use).

---

## 5  Versioning and Compatibility

### 5.1  Environment Isolation

Each `scode` environment is fully isolated. This means:

- Extensions, settings, and user data installed in one environment do **not** affect any other.
- All content lives under `~/.scode/envs/<quality>/<name>/`, keeping environments self-contained and reproducible.

### 5.2  VS Code Version Decoupling

`scode` environments are **not bound** to specific versions of VS Code. You can serve any environment with any supported VS Code version using:

```bash
scode serve-web --version <vscode_version> -- --account <pi-account>
```

`scode` periodically downloads new VS Code builds into `$SCODE_ARCHIVE_DIR`. When you launch an environment, it locates the specified version from this archive, extracts it to `~/.scode/versions/<quality>/<vscode_version>`, and serves it from there.

By default, the `--version` argument for `scode serve-web` is set to `latest`. This means `scode` will automatically pull and use the most recent VS Code version from the archive. **This is the recommended behavior** for most users.

To view all VS Code versions currently available on the Midway cluster:

```bash
scode download --versions
```

This version decoupling gives you the flexibility to:

- Easily opt in or out of the latest VS Code versions.
- Test your environment across multiple editor versions.
- Ensure long-term reproducibility by explicitly pinning a specific VS Code version.

### 5.3  Extension Compatibility

While environments and VS Code versions are decoupled, **extensions are typically tightly coupled to the VS Code version** they were built for. Refer to the [Extensions documentation](./extensions.md#extension-compatibility) for best practices.

---

## 7  Troubleshooting

1. **Extensions missing after installation?**

    Always verify that you're working in the correct environment by running `scode list`. Use the `--env` option to explicitly target a specific environment when installing extensions or serving VS Code. If you have created or switched to a new environment, you must re-install your extensions there.

2. **Disk quota exceeded in `$HOME`?**

    This often occurs when too many environments or cached tarballs accumulate. Remove unused environments to free up space.

    Alternatively, you can move the `~/.scode` directory to `/scratch` and create a symbolic link back to your home directory:

    ```bash
    mv ~/.scode /scratch/midway3/$USER/.scode
    ln -s /scratch/midway3/$USER/.scode ~/.scode
    ```

    This approach helps keep your home directory within quota limits.
