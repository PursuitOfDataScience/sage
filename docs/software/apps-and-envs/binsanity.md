# BinSanity

[BinSanity](https://github.com/edgraham/BinSanity) is a metagenomics contig binning tool that recovers Metagenome-Assembled Genomes (MAGs) from assembled contigs using coverage-based Affinity Propagation (AP) clustering, optionally refined with GC content and CheckM quality assessment.

Keywords: `metagenomics`, `binning`, `MAG`, `assembly`, `microbial ecology`

---

## Available modules

```
---------------------------- /software/modulefiles -----------------------------
binsanity/0.5.4(default)
```

To see what a module sets up:
```bash
module show binsanity/0.5.4
```

For built-in documentation:
```bash
module help binsanity/0.5.4
```

---

## Executables

Loading the module adds the following to your `PATH`:

| Executable | Description |
|------------|-------------|
| `Binsanity` | Core coverage-based AP clustering |
| `Binsanity-wf` | Full workflow: coverage + GC content + CheckM quality assessment |
| `Binsanity-lc` | Low-coverage variant of the core workflow |
| `Binsanity-refine` | Bin refinement using coverage, GC content, and k-mer composition |
| `Binsanity2-beta` | Beta workflow variant |
| `Binsanity-profile` | Per-contig coverage profiling from sorted BAM files (featureCounts) |

---

## Quick start

BinSanity requires two inputs:

1. An assembled contig FASTA file
2. Per-contig coverage depth (from sorted BAM files)

### Step 1 — Compute coverage depth

```bash
module load binsanity/0.5.4
module load samtools/1.22.1

# Sort and index your BAM file if not already done
samtools sort -o reads_sorted.bam reads.bam
samtools index reads_sorted.bam

# Place sorted BAM(s) in a directory, then compute per-contig coverage
mkdir bam_files/
mv reads_sorted.bam bam_files/
Binsanity-profile -i contigs.fa -s bam_files/ -c coverage
```

`-s` takes a directory of sorted BAM files (not a single file path). `-c` is a basename — the tool appends `.cov` automatically, producing `coverage.cov`.

For multiple samples (improves binning accuracy):

```bash
mkdir bam_files/
mv sample1_sorted.bam sample2_sorted.bam sample3_sorted.bam bam_files/
Binsanity-profile -i contigs.fa -s bam_files/ -c coverage
```

### Step 2 — Bin contigs by coverage

```bash
Binsanity -f <contig_dir> -l contigs.fa -c coverage.cov -o bins/
```

`<contig_dir>` is the directory containing the contig FASTA file.

### Step 3 (optional) — Refine bins with GC content and k-mer composition

```bash
Binsanity-refine -f <contig_dir> -l contigs.fa -c coverage.cov -o bins_refined/
```

`-f` must point to the directory containing the original contig FASTA (same as Step 2), not the `bins/` output directory.

---

## Example job script (Midway3)

This example runs the core binning step. For the full workflow (`Binsanity-wf`), increase `--mem` to at least 40 GB and consider `--partition=bigmem`.

```bash
#!/bin/bash
#SBATCH --job-name=binsanity
#SBATCH --account=pi-[cnetid]
#SBATCH --partition=caslake
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=4
#SBATCH --mem=16G
#SBATCH --time=02:00:00

module load binsanity/0.5.4
module load samtools/1.22.1

cd /scratch/$USER/my_metagenome

# Step 1 — coverage profiling (BAMs must be in a directory)
mkdir -p bam_files/
mv sample1_sorted.bam sample2_sorted.bam bam_files/
Binsanity-profile -i contigs.fa -s bam_files/ -c coverage

# Step 2 — bin contigs
Binsanity -f . -l contigs.fa -c coverage.cov -o bins/
```

---

## Notes

- **Memory — CheckM steps**: `Binsanity-wf` invokes CheckM internally, which requires approximately 40 GB RAM for the full reference tree (or ~16 GB with `--reduced_tree`). Always run it on a compute partition: `--partition=bigmem --mem=48G` (full tree) or `--partition=caslake --mem=20G --reduced_tree` (reduced tree). The core `Binsanity` and `Binsanity-refine` commands do not invoke CheckM and run comfortably with 8–16 GB.
- **Memory — large assemblies**: BinSanity's Affinity Propagation builds a pairwise distance matrix that scales O(N²) with contig count. Very large assemblies (hundreds of thousands of contigs) may require substantially more RAM. If memory is a concern, [MetaBAT2](metabat2.md) is a faster alternative with much lower memory requirements.
- **Multiple samples**: Using BAM files from multiple samples improves binning quality, particularly for low-abundance organisms.
- **Minimum contig length**: Short contigs contribute noise. Filter to ≥2500 bp before binning (e.g., with `seqkit` or `awk`).
- **`CHECKM_DATA_PATH`**: The module sets this automatically — no manual configuration needed.
