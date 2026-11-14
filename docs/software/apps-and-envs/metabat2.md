# MetaBAT2

[MetaBAT2](https://bitbucket.org/berkeleylab/metabat) is a metagenome binning tool that groups assembled contigs into bins representing individual genomes (metagenome-assembled genomes, MAGs). It uses tetranucleotide frequency (TNF) and coverage depth across samples to cluster contigs.

Keywords: `metagenomics`, `binning`, `MAG`, `assembly`, `microbial ecology`

---

## Available modules

```
---------------------------- /software/modulefiles -----------------------------
metabat2/2.18(default)
```

To see what a module sets up:
```bash
module show metabat2/2.18
```

For built-in documentation:
```bash
module help metabat2/2.18
```

---

## Executables

Loading the module adds the following to your `PATH`:

| Executable | Description |
|------------|-------------|
| `metabat2` | Main binning tool |
| `metabat1` | Legacy ensemble binning (MetaBAT 1) |
| `jgi_summarize_bam_contig_depths` | Computes per-contig coverage depth from sorted BAM files |
| `runMetaBat.sh` | Convenience wrapper: runs depth summarization + metabat2 in one step |

---

## Quick start

MetaBAT2 requires two inputs:

1. A contig assembly (FASTA)
2. Coverage depth information derived from sorted BAM file(s)

### Step 1 — Generate depth file

```bash
module load metabat2/2.18
module load samtools/1.22.1

# Sort and index your BAM file if not already done
samtools sort -o reads_sorted.bam reads.bam
samtools index reads_sorted.bam

# Compute per-contig depth
jgi_summarize_bam_contig_depths \
    --outputDepth depth.txt \
    reads_sorted.bam
```

For multiple samples (recommended — improves binning accuracy):

```bash
jgi_summarize_bam_contig_depths \
    --outputDepth depth.txt \
    sample1_sorted.bam sample2_sorted.bam sample3_sorted.bam
```

### Step 2 — Run MetaBAT2

```bash
mkdir -p bins/
metabat2 \
    -i assembly.fa \
    -a depth.txt \
    -o bins/bin \
    --minContig 2500 \
    --numThreads 4
```

Output: `bins/bin.1.fa`, `bins/bin.2.fa`, … — one FASTA per bin.

---

## Example job script (Midway3)

```bash
#!/bin/bash
#SBATCH --job-name=metabat2
#SBATCH --account=pi-[cnetid]
#SBATCH --partition=caslake
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00

module load metabat2/2.18
module load samtools/1.22.1

cd /scratch/$USER/my_metagenome

jgi_summarize_bam_contig_depths \
    --outputDepth depth.txt \
    sample1_sorted.bam sample2_sorted.bam

mkdir -p bins/
metabat2 \
    -i assembly.fa \
    -a depth.txt \
    -o bins/bin \
    --minContig 2500 \
    --numThreads 8
```

---

## Notes

- **Multiple samples**: Using BAM files from multiple samples substantially improves bin quality. A single-sample run may produce few or no bins.
- **Minimum contig length**: The default `--minContig 2500` skips contigs shorter than 2500 bp. Lowering this recovers more sequence but reduces bin purity.
- **`runMetaBat.sh` wrapper**: Combines both steps in one command — useful for simple single-sample runs: `runMetaBat.sh assembly.fa reads_sorted.bam`
- **Memory**: Large assemblies (>500 Mbp) may require 64 GB or more. Adjust `--mem` accordingly.
