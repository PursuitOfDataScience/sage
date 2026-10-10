# MeshLab

[MeshLab](https://www.meshlab.net/) is an open-source system for processing and editing 3D triangular meshes and point clouds. It provides tools for cleaning, inspecting, rendering, and converting 3D geometry data, and is widely used in research areas such as computational geometry, 3D scanning, CAD, and scientific visualization.

Keywords: `3D`, `mesh`, `point cloud`, `geometry`, `visualization`, `CAD`

!!! warning "Midway3 only"
    MeshLab is available on **Midway3 only**. It is not available on Midway2.

---

## Available modules

```
---------------------------- /software/modulefiles -----------------------------
meshlab/2025.07(default)
```

---

## Requirements — graphical session

MeshLab is a GUI application and requires a graphical display. You must connect to Midway3 via one of the following before launching it:

- **[ThinLinc](../../connection/thinlinc/main.md)** (recommended — full remote desktop, best performance)
- **X11 forwarding** via SSH: `ssh -X <cnetid>@midway3.rcc.uchicago.edu`

!!! warning
    MeshLab will not launch from a standard (non-graphical) SSH session.

---

## Launching MeshLab

Once connected via ThinLinc or X11, start an interactive compute session before launching MeshLab — do not run it directly on the login node:

```bash
sinteractive --account=pi-[cnetid] --partition=caslake --nodes=1 --ntasks-per-node=1 --time=02:00:00
```

Then load the module and run:

```bash
module load meshlab/2025.07
meshlab
```

MeshLab opens as a desktop window. You can then load files via **File → Open** or pass a file directly on the command line:

```bash
meshlab mymodel.ply
```

---

## Supported file formats

MeshLab supports a wide range of 3D formats, including:

| Format | Extension |
|--------|-----------|
| Stanford PLY | `.ply` |
| OBJ (Wavefront) | `.obj` |
| STL | `.stl` |
| Collada | `.dae` |
| 3DS | `.3ds` |
| VTK | `.vtk` |
| XYZ point cloud | `.xyz`, `.asc` |
| E57 point cloud | `.e57` |

For a full list, see **File → Open** in the MeshLab interface.

---

## Accessing your files

Your `/home`, `/scratch`, and `/project` directories are accessible inside MeshLab by default. If you have data under `/project2`, that is also available.

---

## Notes

- MeshLab on Midway3 runs inside an [Apptainer](singularity.md) container — this is handled transparently by the module wrapper and requires no extra steps from the user.
- For rendering with per-vertex colors, enable **Render → Color → Per Vertex** in the MeshLab menu.
- MeshLab is an interactive tool and is not suited for batch/non-interactive SLURM jobs. Always launch it from an `sinteractive` session, not from a login node.
