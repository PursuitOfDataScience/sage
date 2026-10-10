# WRF

[WRF (Weather Research and Forecasting Model)](https://www.mmm.ucar.edu/models/wrf) is a widely used mesoscale numerical weather prediction system developed by NCAR and NOAA. It supports both idealized simulations and real-data forecasts, and is used for research and operational weather prediction.

Keywords: `weather`, `climate`, `numerical weather prediction`, `atmospheric science`, `mesoscale`

---

## Available modules

<div markdown="1">
=== "Midway2"
    ```
    -------------------- /software/modulefiles2 --------------------
    wrf/4.1.5(default)  wrf/4.7.1
    ```

===+ "Midway3"
    ```
    -------------------- /software/modulefiles ---------------------
    wrf/4.1.5  wrf/4.7.1(default)
    ```
</div>

To see what a module sets up:
```bash
module show wrf/4.7.1
```

---

## Executables

Loading a WRF module adds the following executables to your `PATH`:

| Executable | Description |
|------------|-------------|
| `wrf.exe` | Main WRF model (MPI) |
| `real.exe` | Real-data initialization — reads WPS `met_em` files (MPI) |
| `ndown.exe` | One-way nesting / downscaling (MPI) |
| `tc.exe` | Tropical cyclone bogussing (MPI) |
| `geogrid.exe` | WPS — geographical data processing (MPI) |
| `ungrib.exe` | WPS — GRIB file decoding (serial) |
| `metgrid.exe` | WPS — meteorological field interpolation (MPI) |

!!! note "`ideal.exe` — per-case compilation required"
    `ideal.exe` is not included in the pre-built conda WRF binaries. To compile it for a specific idealized case:
    ```bash
    module load wrf/4.7.1
    cd $WRF_DIR
    ./compile em_quarter_ss   # replace with your test case name
    # result: $WRF_DIR/main/ideal.exe
    ```
    Available idealized cases: `em_quarter_ss`, `em_b_wave`, `em_tropical_cyclone`, and others under `$WRF_DIR/test/`.

---

## Idealized run (quick start)

The following runs the `em_quarter_ss` squall line case with WRF 4.7.1:

```bash
module load wrf/4.7.1

# Compile ideal.exe for this case (one-time)
cd $WRF_DIR && ./compile em_quarter_ss

# Set up run directory
mkdir -p /scratch/$USER/wrf_ideal && cd /scratch/$USER/wrf_ideal
ln -sf $WRF_DIR/run/* .
cp --remove-destination $WRF_DIR/test/em_quarter_ss/namelist.input .
cp --remove-destination $WRF_DIR/main/ideal.exe .

# Submit
sbatch run_ideal.sh
```

Example job script for **Midway3** (`run_ideal.sh`):
```bash
#!/bin/bash
#SBATCH --job-name=wrf-ideal
#SBATCH --account=pi-[cnetid]
#SBATCH --partition=caslake
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=8
#SBATCH --time=00:30:00
#SBATCH --exclusive

module load wrf/4.7.1

export OMPI_MCA_pml=ob1
export OMPI_MCA_btl=sm,self

cd /scratch/$USER/wrf_ideal
mpirun -np 8 ./ideal.exe
mpirun -np 8 ./wrf.exe
```

For **Midway2**, the module built-in help is self-contained and includes the full workflow and ready-to-run example commands — run:
```bash
module help wrf/4.7.1
module help wrf/4.1.5
```

!!! note "`em_tropical_cyclone` — single MPI task only"
    The tropical cyclone idealized case (`em_tropical_cyclone`) has a 201×201 domain that does not decompose cleanly across multiple MPI tasks. Run it with `mpirun -np 1` for both `ideal.exe` and `wrf.exe`.

---

## Real-data run (WPS → WRF chain)

Real-data WRF runs require WPS preprocessing before running `real.exe` and `wrf.exe`. The full chain is:

```
geogrid.exe → ungrib.exe → metgrid.exe → real.exe → wrf.exe
```

!!! warning "Always use `wrf/4.1.5` for the `metgrid` step"
    The `metgrid.exe` shipped with `wrf/4.7.1` (WPS V4.6.0) has a known NetCDF4 write bug that silently produces empty `met_em` files. Always use `wrf/4.1.5`'s `metgrid.exe` for the WPS step regardless of which WRF version you intend to run.

### Step 1 — geogrid (geographical preprocessing)

```bash
module load wrf/4.7.1   # or wrf/4.1.5

mkdir -p /scratch/$USER/wps_run && cd /scratch/$USER/wps_run

# WPS table files must be in subdirectories (not flat)
mkdir -p geogrid metgrid
ln -sf $WPS_DIR/geogrid/GEOGRID.TBL geogrid/GEOGRID.TBL
ln -sf $WPS_DIR/metgrid/METGRID.TBL metgrid/METGRID.TBL

cp $WPS_DIR/namelist.wps .
# Edit namelist.wps: set geog_data_path, start/end dates, domain config
mpirun -np 4 geogrid.exe
```

!!! note "Geographic data resolution"
    Use `geog_data_res = 'lowres'` in `namelist.wps` if working with the low-resolution GEOG dataset (`WPS_GEOG_LOW_RES`). The default `'default'` key expects 30-arc-second data which may not be present.

### Step 2 — ungrib (GRIB decoding)

```bash
module load wrf/4.1.5   # switch to 4.1.5 for ungrib + metgrid

ln -sf $WPS_DIR/ungrib/Variable_Tables/Vtable.GFS Vtable
$WPS_DIR/link_grib.csh /path/to/grib/files/gfs.*
ungrib.exe
```

### Step 3 — metgrid (meteorological interpolation)

```bash
# Still with wrf/4.1.5 loaded
mpirun -np 4 metgrid.exe
# Verify output: met_em.d01.YYYY-MM-DD_HH:MM:SS.nc files should be ~2–3 MB each
ls -lh met_em.*
```

### Step 4 — real.exe and wrf.exe

```bash
module load wrf/4.7.1   # switch back to desired WRF version

mkdir -p /scratch/$USER/wrf_real && cd /scratch/$USER/wrf_real
ln -sf $WRF_DIR/run/* .
ln -sf /scratch/$USER/wps_run/met_em.* .

# Edit namelist.input: start/end dates, domain, physics options
sbatch run_real_wrf.sh
```

Example job script for **Midway3** (`run_real_wrf.sh`):
```bash
#!/bin/bash
#SBATCH --job-name=wrf-real
#SBATCH --account=pi-[cnetid]
#SBATCH --partition=caslake
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=4
#SBATCH --time=02:00:00
#SBATCH --exclusive

module load wrf/4.7.1

export OMPI_MCA_pml=ob1
export OMPI_MCA_btl=sm,self

cd /scratch/$USER/wrf_real
mpirun -np 4 real.exe
mpirun -np 4 wrf.exe
```

Check for successful completion:
```bash
grep "SUCCESS" rsl.error.0000
# Expected: wrf: SUCCESS COMPLETE WRF
```

---

## Notes

- **OMPI_MCA bypass**: RCC clusters require `OMPI_MCA_pml=ob1` and `OMPI_MCA_btl=sm,self` (single-node) or `sm,tcp,self` (multi-node) in all WRF SLURM scripts. This is a known OpenMPI/UCX memory-pinning limitation on these nodes.
- **WPS table subdirectories**: `geogrid.exe` and `metgrid.exe` look for their table files in `./geogrid/GEOGRID.TBL` and `./metgrid/METGRID.TBL` respectively — not in the current directory directly.
- **`ideal.exe` symlink trap**: Avoid using symlinks to `ideal.exe` across multiple run directories. If you recompile for a different case, all symlinked directories will silently pick up the wrong binary. Use `cp --remove-destination` instead.
- **num_land_cat**: When using `WPS_GEOG_LOW_RES`, set `num_land_cat = 24` in `namelist.input` and avoid physics suites that expect 20 or 21 land categories (e.g., the CONUS physics suite).
- **Lustre stat cache**: On `/scratch` (Lustre), add `sync && sleep 2` between `geogrid.exe` and `metgrid.exe` to avoid race conditions where metgrid cannot immediately see the `geo_em` file.
