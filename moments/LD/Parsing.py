imported_h5py = 0
imported_allel = 0
import os
try:
    os.environ["NUMEXPR_MAX_THREADS"]="272"
    import allel
    imported_allel = 1
except ImportError:
    pass

try:
    import h5py
    imported_h5py = 1
except ImportError:
    pass

from . import Util

def check_imports():
    if imported_allel == 0:
        raise("Failed to import allel package needed for Parsing. Is it installed?")
    if imported_h5py == 0:
        raise("Failed to import h5py package needed for Parsing. Is it installed?")

# later go through and trim the unneeded ones
import numpy as np
import pandas
from collections import Counter,defaultdict
#from . import stats_from_genotype_counts as sgc
from . import stats_from_haplotype_counts as shc
import sys
import itertools
ld_extensions = 0
try:
    import genotype_calculations as gcs
    import genotype_calculations_multipop as gcs_mp
    import sparse_tallying as spt
    ld_extensions = 1
except ImportError:
    pass

# turn off UserWarnings from allel
import warnings
if imported_allel:
    warnings.filterwarnings(action='ignore', category=UserWarning)


### does this handle only a single chromosome at a time???

def load_h5(vcf_file, report=True):
    check_imports()
    ## open the h5 callset, create if doesn't exist
    ## note that if the h5 file exists, but isn't properly written, you will need to delete and recreate
    ## saves h5 callset as same name and path, but with h5 extension instead of vcf or vcf.gz
    h5_file_path = vcf_file.split('.vcf')[0] + '.h5' # kinda hacky, sure
    try:
        callset = h5py.File(h5_file_path, mode='r')
    except (OSError,IOError): # IOError merged into OSError in python 3
        if report is True: print("creating and saving h5 file"); sys.stdout.flush()
        allel.vcf_to_hdf5(vcf_file, h5_file_path, 
                fields='*', exclude_fields=['calldata/GQ'],
                overwrite=True)
        callset = h5py.File(h5_file_path, mode='r')
    return callset


### genotype function
def get_genotypes(vcf_file, bed_file=None, chromosome=None, min_bp=None, use_h5=True, report=True):
    """
    Given a vcf file, we extract the biallelic SNP genotypes.
    If bed_file is None, we use all valid variants. Otherwise we filter genotypes
        by the given bed file.
    If chromosome (int) is given, filters to keep snps only in given chrom (useful for vcfs spanning 
        multiple chromosomes).
    min_bp : only used with bed file, filters out features that are smaller than min_bp
    If use_h5 is True, we try to load the h5 file, which has the same path/name as 
        vcf_file, but with *.h5 instead of *.vcf or *.vcf.gz. If the h5 file does not
        exist, we create it and save it as *.h5
    report : prints progress updates if True, silent otherwise
    """
    
    check_imports()
    
    if use_h5 is True:
        callset = load_h5(vcf_file, report=report)
    else:
        ## read the vcf directly
        raise ValueError("Use hdf5 format.")
    
    all_genotypes = allel.GenotypeChunkedArray(callset['calldata/GT'])
    all_positions = callset['variants/POS'][:]
    
    if report is True: print("loaded genotypes"); sys.stdout.flush()
    
    # filter SNPs not in bed file, if one is given
    if bed_file is not None: # filter genotypes and positions
        mask_bed = pandas.read_csv(bed_file, sep='\t', header=None)
        chroms = [c for c in list(set(callset['variants/CHROM'][:]))]
        
        # because of the variation of chrom labels (with our without chr (22 vs chr22)),
        # we check that chroms start with chr
        
        for ii,c in enumerate(chroms):
            if 'chr' in c:
                chroms[ii] = c[3:]
        
        chrom_filter = [False] * len(mask_bed)
        if chromosome is not None:
            chrom_filter = np.logical_or(chrom_filter, np.logical_or(mask_bed[0].values.astype(str) == str(chromosome), mask_bed[0].values.astype(str) == 'chr'+str(chromosome)))
        else:
            for chrom in chroms:
                chrom_filter = np.logical_or(chrom_filter, np.logical_or(mask_bed[0].values.astype(str) == chrom, mask_bed[0].values.astype(str) == 'chr'+chrom))
        
        mask_bed = mask_bed.loc[chrom_filter]

        # if we want a minimum length of feature, only keep long enough features
        if min_bp is not None:
            mask_bed = mask_bed.loc[mask_bed[2] - mask_bed[1] >= min_bp]
        
        n_features = mask_bed.shape[0]

        in_mask = (all_positions < 0)
        for _index, feature in mask_bed.iterrows():
            start = feature[1]
            end = feature[2]
              
            in_mask = np.logical_or(in_mask, np.logical_and(all_positions>=start, 
                                                            all_positions<end))
        if report is True: print("created bed filter"); sys.stdout.flush()
        
        all_positions = all_positions.compress(in_mask)
        all_genotypes = all_genotypes.compress(in_mask)
        
        if report is True: print("filtered by bed"); sys.stdout.flush()
    elif chromosome is not None:
        # only keep variants that are in the given chromosome number
        all_chromosomes = callset['variants/CHROM'][:]
        in_chromosome = (all_chromosomes == str(chromosome))
        all_positions = all_positions.compress(in_chromosome)
        all_genotypes = all_genotypes.compress(in_chromosome)
        
    all_genotypes_012 = all_genotypes.to_n_alt(fill=-1)
    
    # count alleles and only keep biallelic positions
    allele_counts = all_genotypes.count_alleles()
    is_biallelic = allele_counts.is_biallelic_01()
    biallelic_positions = all_positions.compress(is_biallelic)
    
    biallelic_genotypes_012 = all_genotypes_012.compress(is_biallelic)
    
    biallelic_allele_counts = allele_counts.compress(is_biallelic)
    biallelic_genotypes = all_genotypes.compress(is_biallelic)
    
    if report is True: print("kept biallelic positions"); sys.stdout.flush()
    
    relevant_column = np.array([False] * biallelic_allele_counts.shape[1])
    relevant_column[0:2] = True
    biallelic_allele_counts = biallelic_allele_counts.compress(relevant_column, axis = 1)
    
    sample_ids = callset['samples']
    
    return biallelic_positions, biallelic_genotypes, biallelic_allele_counts, sample_ids


def assign_r_pos(positions, rec_map):
    rs = np.zeros(len(positions))
    for ii,pos in enumerate(positions):
        if pos in np.array(rec_map[0]):
            rs[ii] = np.array(rec_map[1])[np.argwhere(pos == np.array(rec_map[0]))[0]] 
        else:
            ## for now, if outside rec map, assign to nearest point, but later want to drop these positions
            if pos < rec_map[0].iloc[0]:
                rs[ii] = rec_map[1].iloc[0]
            elif pos > rec_map[0].iloc[-1]:
                rs[ii] = rec_map[1].iloc[-1]
            else:
                map_ii = np.where(pos >= np.array(rec_map[0]))[0][-1]
                l = rec_map[0][map_ii]
                r = rec_map[0][map_ii+1]
                v_l = rec_map[1][map_ii]
                v_r = rec_map[1][map_ii+1]
                rs[ii] = v_l + (v_r-v_l) * (pos-l)/(r-l)
    return rs


def assign_recombination_rates(positions, map_file, map_name=None, map_sep='\t', cM=True, report=True):
    if map_file == None:
        raise ValueError("Need to pass a recombination map file. Otherwise can bin by physical distance."); sys.stdout.flush()
    try:
        rec_map = pandas.read_csv(map_file, sep=map_sep)
    except:
        raise ValueError("Error loading map."); sys.stdout.flush()
    
    map_positions = rec_map[rec_map.keys()[0]]
    if map_name == None: # we use the first map column
        if report is True: print("No recombination map name given, using first column."); sys.stdout.flush()
        map_values = rec_map[rec_map.keys()[1]]
    else:
        try:
            map_values = rec_map[map_name]
        except KeyError:
            print("WARNING: map_name did not match map names in recombination map file. Using first column...")
            map_values = rec_map[rec_map.keys()[1]]
        
    # for positions sticking out the end of the map, they take the value of the closest position
    # ideally, you'd filter these out
    
    if cM == True:
        map_values /= 100
    
    pos_rs = assign_r_pos(positions, [map_positions, map_values])
    
    return pos_rs

## We store a Genotype matrix, which has size L x n, in sparse format
## Indexed by position in Genotype array (0...L-1)
## and G_dict[i] = {1: J, 2: K}
## where J and K are sets of the diploid individual indices that
## have genotypes 1 or 2
## If there is any missing data, we also store set of individuals with -1's

def sparsify_genotype_matrix(G):
    G_dict = {}
    if np.any(G==-1):
        missing = True
    else:
        missing = False
    for i in range(len(G)):
        G_dict[i] = {1: set(np.where(G[i,:] == 1)[0]), 
                     2: set(np.where(G[i,:] == 2)[0])}
        if missing == True:
            G_dict[i][-1] = set(np.where(G[i,:] == -11)[0])
    return G_dict, missing

def sparsify_haplotype_matrix(G):
    pass

def tally_sparse_haplotypes():
    pass

#def tally_sparse(G1, G2, n, missing=False):
#    """
#    G1 and G2 are dictionaries with sample indices of genotypes 1 and 2
#    and -1 if missing is True
#    n is the diploid sample size
#    """
#    
#    if missing == True:
#        # account for missing genotypes
#        n22 = (G1[2] & G2[2]).__len__()
#        n21 = (G1[2] & G2[1]).__len__()
#        n2m = (G1[2] & G2[-1]).__len__()
#        n20 = (G1[2]).__len__()-n22-n21-n2m
#        n12 = (G1[1] & G2[2]).__len__()
#        n11 = (G1[1] & G2[1]).__len__()
#        n1m = (G1[1] & G2[-1]).__len__()
#        n10 = (G1[1]).__len__()-n12-n11-n1m
#        nm2 = (G1[-1] & G2[2]).__len__()
#        nm1 = (G1[-1] & G2[1]).__len__()
#        n02 = (G2[2]).__len__()-n22-n12-nm2
#        n01 = (G2[1]).__len__()-n21-n11-nm1
#        # total possible is n-len(set of either missing)
#        nm = len(G1[-1].union(G2[-1]))
#        n00 = (n-nm)-n22-n21-n20-n12-n11-n10-n02-n01
#    else:
#        n22 = (G1[2] & G2[2]).__len__()
#        n21 = (G1[2] & G2[1]).__len__()
#        n20 = (G1[2]).__len__()-n22-n21
#        n12 = (G1[1] & G2[2]).__len__()
#        n11 = (G1[1] & G2[1]).__len__()
#        n10 = (G1[1]).__len__()-n12-n11
#        n02 = (G2[2]).__len__()-n22-n12
#        n01 = (G2[1]).__len__()-n21-n11
#        n00 = n-n22-n21-n20-n12-n11-n10-n02-n01
#    return (n22, n21, n20, n12, n11, n10, n02, n01, n00)
#
#
#def count_genotypes_sparse(G_dict, n, missing=False):
#    """
#    Similar to count_genotypes, but using the sparse genotype representation instead
#    """
#    L = len(G_dict)
#    
#    Counts = np.empty((L*(L-1)//2, 9)).astype('int')
#    c = 0
#    for i in range(L-1):
#        for j in range(i+1,L):
#            Counts[c] = tally_sparse(G_dict[i], G_dict[j], n, missing=missing)
#            c += 1
#    return Counts


def compute_pairwise_stats(Gs):
    """
    Computes D^2, Dz, pi_2, and D for every pair of loci
        within a block of SNPs, coded as a genotype matrix.
    Gs : genotype matrix, of size L \times n, where
        L is the number of loci and n is the sample size
    We use the sparse genotype matrix representation, where
    we first "sparsify" the genotype matrix, and then count
    two-locus genotype configurations from that, from which
    we compute two-locus statistics
    """
    assert ld_extensions == 1, "Need to build LD cython extensions. Install moments with the flag `--ld_extensions`"
    
    L,n = np.shape(Gs)
    
    G_dict, any_missing = sparsify_genotype_matrix(Gs)
    
    Counts = spt.count_genotypes_sparse(G_dict, n, missing=any_missing)
    
    D = gcs.compute_D(Counts)
    D2 = gcs.compute_D2(Counts)
    Dz = gcs.compute_Dz(Counts)
    pi2 = gcs.compute_pi2(Counts)
    
    return D2, Dz, pi2, D

def compute_average_stats(Gs):
    """
    Takes the outputs of compute_pairwise_stats and returns
    the average value for each statistic
    """
    D2, Dz, pi2, D = compute_pairwise_stats(Gs)
    return np.mean(D2), np.mean(Dz), np.mean(pi2), np.mean(D)

def compute_pairwise_stats_between(Gs1, Gs2):
    """
    The Gs are matrices, where rows correspond to loci and columns to individuals
    Both matrices must have the same number of individuals
    If Gs1 has length L1 and Gs2 has length L2, we compute all pairwise counts,
    return Counts, which has size (L1*L2, 9) 

    Computes D^2, Dz, pi_2, and D for every pair of loci
        between two blocks of SNPs, coded as a genotype matrices.
    Gs : genotype matrices, of size L1 or L2 by n, where
        L is the number of loci and n is the sample size
    We use the sparse genotype matrix representation, where
    we first "sparsify" the genotype matrix, and then count
    two-locus genotype configurations from that, from which
    we compute two-locus statistics
    """
    assert ld_extensions == 1, "Need to build LD cython extensions. Install moments with the flag `--ld_extensions`"

    L1, n1 = np.shape(Gs1)
    L2, n2 = np.shape(Gs1)
    
    if n1 != n2:
        raise ValueError("data must have same number of sequenced individuals")
    else:
        n = n1
    
    G_dict1, any_missing1 = sparsify_genotype_matrix(Gs1)
    G_dict2, any_missing2 = sparsify_genotype_matrix(Gs2)
    
    any_missing = np.logical_or(any_missing1, any_missing2)
    
    Counts = spt.count_genotypes_between_sparse(G_dict1, G_dict2, n, missing=any_missing)
    
    D2 = gcs.compute_D2(Counts)
    Dz = gcs.compute_Dz(Counts)
    pi2 = gcs.compute_pi2(Counts)
    D = gcs.compute_D(Counts)
    
    return D2, Dz, pi2, D

def compute_average_stats_between(Gs1,Gs2):
    """
    Takes the outputs of compute_pairwise_stats_between and returns
    the average value for each statistic
    """
    D2, Dz, pi2, D = compute_pairwise_stats_between(Gs1, Gs2)
    return np.mean(D2), np.mean(Dz), np.mean(pi2), np.mean(D)



def count_types_sparse(genotypes, bins, sample_ids, positions=None, pos_rs=None, 
        pop_file=None, pops=None, use_genotypes=True, report=True, report_spacing=1000, 
        use_cache=True, stats_to_compute=None, normalized_by=None, ac_filter=None):
    """
    genotypes: 
    bins: 
    sample_ids: list of ordered samples, as output by get_genotypes
    positions: list of base pair positions for each SNP in genotypes
    pos_rs: list of genetic map positions for each SNP in genotypes
    pop_file: sample-population file
    pops: list of populations to keep. If None, uses all samples and treats them 
        as a single population
    use_genotypes: if True, assumes unphased data. If False, assumes phasing is given 
        in genotypes.
    use_cache: if True, caches genotype tally counts to compute statistics at end
        together. If False, computes statistics for each pair on the fly. Can result
        in recomputing many times, but memory can become an issue when there are many
        populations.
    stats_to_compute: list of lists of two-locus and single-locus statist to compute.
        If None, computes all relevant statistics.
    normalized_by: population that we are normalizing by. We need to have at least 
        four two-locus counts for the focal pop in order to include this pair. 
        If we set to None, then we should be sure that we won't run into this issue,
        for example if we know that we don't have missing data.
    """
    assert ld_extensions == 1, "Need to build LD cython extensions. Install moments with the flag `--ld_extensions`"

    pop_indexes = {}
    if pops is not None:
        ## get columns to keep, and compress data and sample_ids
        samples = pandas.read_csv(pop_file, delim_whitespace=True)
        cols_to_keep = np.array([False]*np.shape(genotypes)[1])
        all_samples_to_keep = []
        for pop in pops:
            all_samples_to_keep += list(samples[samples['pop'] == pop]['sample'])
        
        sample_list = list(sample_ids)
        for s in all_samples_to_keep:
            cols_to_keep[sample_list.index(s)] = True
        
        genotypes_pops = genotypes.compress(cols_to_keep, axis=1)
        sample_ids_pops = list(np.array(sample_list).compress(cols_to_keep))
        
        ## keep only biallelic genotypes from populations in pops, discard the rest
        allele_counts_pops = genotypes_pops.count_alleles()
        is_biallelic = allele_counts_pops.is_biallelic_01()
        genotypes_pops = genotypes_pops.compress(is_biallelic)
        
        ## for each population, get the indexes for each population
        for pop in pops:
            pop_indexes[pop] = np.array([False]*np.shape(genotypes_pops)[1])
            for s in samples[samples['pop'] == pop]['sample']:
                pop_indexes[pop][sample_ids_pops.index(s)] = True
        
        if use_genotypes == False:
            pop_indexes_haps = {}
            for pop in pops:
                pop_indexes_haps[pop] = np.reshape(list(zip(pop_indexes[pop], pop_indexes[pop])),(2*len(pop_indexes[pop]),))
        
        if positions is not None:
            positions = positions.compress(is_biallelic)
        if pos_rs is not None:
            pos_rs = pos_rs.compress(is_biallelic)
        
    else:
        if report == True:
            print("No populations given, using all samples as one population."); sys.stdout.flush()
        pops = ['ALL']
        pop_indexes['ALL'] = np.array([True]*np.shape(genotypes)[1])
        genotypes_pops = genotypes
        if use_genotypes == False:
            pop_indexes_haps = {}
            for pop in pops:
                pop_indexes_haps[pop] = np.reshape(list(zip(pop_indexes[pop], pop_indexes[pop])),(2*len(pop_indexes[pop]),))
    
    ## convert to 0,1,2 format
    if use_genotypes == True:
        genotypes_pops_012 = genotypes_pops.to_n_alt()
    else:
        try:
            haplotypes_pops_01 = genotypes_pops.to_haplotypes()
        except AttributeError:
            print("warning: attempted to get haplotypes from phased genotypes, returned attribute error. Using input as haplotypes.")
            haplotypes_pops_01 = genotypes_pops
        
    if pos_rs is not None:
        rs = pos_rs
    elif positions is not None:
        rs = positions
    
    ns = {}
    for pop in pops:
        if use_genotypes == True:
            ns[pop] = sum(pop_indexes[pop])
        else:
            ns[pop] = 2*sum(pop_indexes[pop])
    
    bins = np.array(bins)
    
    ## split and sparsify the geno/haplo-type arrays for each population
    if use_genotypes == True:
        genotypes_by_pop = {}
        any_missing = False
        for pop in pops:
            temp_genotypes = genotypes_pops_012.compress(pop_indexes[pop], axis=1)
            genotypes_by_pop[pop], this_missing = sparsify_genotype_matrix(temp_genotypes)
            any_missing = np.logical_or(any_missing, this_missing)
    else:
        haplotypes_by_pop = {}
        any_missing = False
        for pop in pops:
            temp_haplotypes = haplotypes_pops_01.compress(pop_indexes[pop], axis=1)
            haplotypes_by_pop[pop], this_missing = sparsify_haplotype_matrix(temp_haplotypes)
            any_missing = np.logical_or(any_missing, this_missing)
    
#    if use_cache == True:
#        run loop that computes type_counts cache
#    else
#        run loop that adds to sums

    ## if use_cache is True, type_counts will store the number of times we 
    ## see each genotype count configuration within each bin
    ## if use_cache is False, we add to the running total of sums of each
    ## statistic as we count their genotypes, never storing the counts of configurations
    bs = list(zip(bins[:-1],bins[1:]))
    if use_cache == True:
        type_counts = {}
        for b in bs:
            type_counts[b] = defaultdict(int)
    else:
        sums = {}
        for b in bs:
            sums[b] = {}
            for stat in stats_to_compute[0]:
                sums[b][stat] = 0
    
    ## loop through left positions and pair with positions to the right within the bin windows
    ## very inefficient, naive approach
    for ii,r in enumerate(rs[:-1]):
        if report is True:
            if ii%report_spacing == 0:
                print("tallied two locus counts {0} of {1} positions".format(ii, len(rs))); sys.stdout.flush()
        
        ## loop through each bin, picking out the positions to the right of the left locus that fall within the given bin
        if pos_rs is not None:
            distances = pos_rs - r
        else:
            distances = positions - r
        
        filt = np.logical_and( np.logical_and(distances >= bs[0][0], distances < bs[-1][1]), positions != positions[ii] )
        filt[ii] = False # don't compare to mutations at same base pair position
        right_indices = np.where(filt == True)[0]
        
        ## if there are no variants within the bin's distance to the right, continue to next bin 
        if len(right_indices) == 0:
            continue
        
        right_start = right_indices[0]
        right_end = right_indices[-1]+1
        
        if use_cache == False:
            # create counts for each bin, call stats from gentoype counts from here
            # format to pass to call_sgc, for each bin, is
            # 
            counts_ii = {}
            for b in bs:
                counts_ii[b] = [[] for pop_ind in range(len(pops))]
        
        ## loop through right loci and count two-locus genotypes
        for jj in range(right_start, right_end):
            # get the bin that this pair belongs to
            r_dist = distances[jj]
            bin_ind = np.where(r_dist >= bins)[0][-1]
            b = bs[bin_ind]
            
            # count genotypes within each population
            if use_genotypes == True:
                cs = tuple([ spt.tally_sparse(genotypes_by_pop[pop][ii], genotypes_by_pop[pop][jj], ns[pop], any_missing) for pop in pops ])
            else:
                cs = tuple([ tally_sparse_haplotypes(haplotypes_by_pop[pop][ii], haplotypes_by_pop[pop][jj], ns[pop], any_missing) for pop in pops ])
            
            if use_cache == True:
                type_counts[b][cs] += 1
            else:
                for pop_ind in range(len(pops)):
                    counts_ii[b][pop_ind].append(cs[pop_ind])
                    
        if use_cache == False:
            for b in bs:
                these_counts = np.array(counts_ii[b])
                if these_counts.shape[1] == 0:
                    continue
                for stat in stats_to_compute[0]:
                    sums[b][stat] += call_sgc(stat, these_counts.swapaxes(1,2), use_genotypes).sum()
    
    if use_cache == True:
        return type_counts
    else:
        return sums


def call_sgc(stat, Cs, use_genotypes=True):
    """
    stat = 'DD', 'Dz', or 'pi2', with underscore indices (like 'DD_1_1')
    Cs = L \times n array, L number of count configurations, n = 4 or 9 (for haplotypes or genotypes) 
    """
    assert ld_extensions == 1, "Need to build LD cython extensions. Install moments with the flag `--ld_extensions`"

    s = stat.split('_')[0]
    pop_nums = [int(p)-1 for p in stat.split('_')[1:]]
    if s == 'DD':
        if use_genotypes == True:
            return gcs_mp.DD(Cs, pop_nums)
        else:
            return shc.DD(Cs, pop_nums)
    if s == 'Dz':
        ii,jj,kk = pop_nums
        if jj == kk:
            if use_genotypes == True:
                return gcs_mp.Dz(Cs, pop_nums)
            else:
                return shc.Dz(Cs, pop_nums)
        else:
            if use_genotypes == True:
                return 1./2 * gcs_mp.Dz(Cs, [ii,jj,kk]) + 1./2 * gcs_mp.Dz(Cs, [ii,kk,jj])
            else:
                return 1./2 * shc.Dz(Cs, [ii,jj,kk]) + 1./2 * shc.Dz(Cs, [ii,kk,jj])
    if s == 'pi2':
        ii,jj,kk,ll = pop_nums ### this doesn't consider the symmetry between p/q yet...
        if ii == jj:
            if kk == ll:
                if ii == kk: # all the same
                    if use_genotypes == True:
                        return gcs_mp.pi2(Cs, [ii,jj,kk,ll])
                    else:
                        return shc.pi2(Cs, [ii,jj,kk,ll])
                else: # (1, 1; 2, 2)
                    if use_genotypes == True:
                        return 1./2 * (gcs_mp.pi2(Cs, [ii,jj,kk,ll]) + gcs_mp.pi2(Cs, [kk,ll,ii,jj]) )
                    else:
                        return 1./2 * (shc.pi2(Cs, [ii,jj,kk,ll]) + shc.pi2(Cs, [kk,ll,ii,jj]) )
            else: # (1, 1; 2, 3) or (1, 1; 1, 2)
                if use_genotypes == True:
                    return 1./4 * ( gcs_mp.pi2(Cs, [ii,jj,kk,ll]) + gcs_mp.pi2(Cs, [ii,jj,ll,kk]) + gcs_mp.pi2(Cs, [kk,ll,ii,jj]) + gcs_mp.pi2(Cs, [ll,kk,ii,jj]) )
                else:
                    return 1./4 * ( shc.pi2(Cs, [ii,jj,kk,ll]) + shc.pi2(Cs, [ii,jj,ll,kk]) + shc.pi2(Cs, [kk,ll,ii,jj]) + shc.pi2(Cs, [ll,kk,ii,jj]) )
        else:
            if kk == ll: # (1, 2; 3, 3) or (1, 2; 2, 2)
                if use_genotypes == True:
                    return 1./4 * ( gcs_mp.pi2(Cs, [ii,jj,kk,ll]) + gcs_mp.pi2(Cs, [jj,ii,kk,ll]) + gcs_mp.pi2(Cs, [kk,ll,ii,jj]) + gcs_mp.pi2(Cs, [kk,ll,jj,ii]) )
                else:
                    return 1./4 * ( shc.pi2(Cs, [ii,jj,kk,ll]) + shc.pi2(Cs, [jj,ii,kk,ll]) + shc.pi2(Cs, [kk,ll,ii,jj]) + shc.pi2(Cs, [kk,ll,jj,ii]) )
            else: # (1, 2; 3, 4)
                if use_genotypes == True:
                    return 1./8 * ( gcs_mp.pi2(Cs, [ii,jj,kk,ll]) + gcs_mp.pi2(Cs, [ii,jj,ll,kk]) + gcs_mp.pi2(Cs, [jj,ii,kk,ll]) + gcs_mp.pi2(Cs, [jj,ii,ll,kk]) + gcs_mp.pi2(Cs, [kk,ll,ii,jj]) + gcs_mp.pi2(Cs, [ll,kk,ii,jj]) + gcs_mp.pi2(Cs, [kk,ll,jj,ii]) + gcs_mp.pi2(Cs, [ll,kk,jj,ii]) )
                else:
                    return 1./8 * ( shc.pi2(Cs, [ii,jj,kk,ll]) + shc.pi2(Cs, [ii,jj,ll,kk]) + shc.pi2(Cs, [jj,ii,kk,ll]) + shc.pi2(Cs, [jj,ii,ll,kk]) + shc.pi2(Cs, [kk,ll,ii,jj]) + shc.pi2(Cs, [ll,kk,ii,jj]) + shc.pi2(Cs, [kk,ll,jj,ii]) + shc.pi2(Cs, [ll,kk,jj,ii]) )


def cache_ld_statistics(type_counts, ld_stats, bins, use_genotypes=True, report=True):
    bs = list(zip(bins[:-1],bins[1:]))
    
    estimates = {}
    for b in bs:
        for cs in type_counts[b].keys():
            estimates.setdefault(cs, {})
    
    all_counts = np.array(list(estimates.keys()))
    all_counts = np.swapaxes(all_counts,0,1)
    all_counts = np.swapaxes(all_counts,1,2)
    
    for stat in ld_stats:
        if report is True: print("computing " + stat); sys.stdout.flush()
        vals = call_sgc(stat, all_counts, use_genotypes)
        for ii in range(len(all_counts[0,0])):
            cs = all_counts[:,:,ii]
            estimates[tuple([tuple(c) for c in cs])][stat] = vals[ii]
    return estimates


def get_ld_stat_sums(type_counts, ld_stats, bins, use_genotypes=True, report=True):
    """
    return sums[b][stat]
    """
    ### this is super inefficient, just trying to get around memory issues
    
    bs = list(zip(bins[:-1],bins[1:]))
    sums = {}
    empty_genotypes = tuple([0]*9)
    
    for stat in ld_stats:
        if report is True: print("computing " + stat); sys.stdout.flush()
        # set counts of non-used stats to zeros, then take set
        pops_in_stat = sorted(list(set(int(p)-1 for p in stat.split('_')[1:])))
        stat_counts = {}
        for b in bs:
            for cs in type_counts[b].keys():
                this_count = list(cs)
                for i in range(len(cs)):
                    if i not in pops_in_stat:
                        this_count[i] = empty_genotypes
                stat_counts.setdefault(tuple(this_count),defaultdict(int))
                stat_counts[tuple(this_count)][b] += type_counts[b][cs]
         
        all_counts = np.array(list(stat_counts.keys()))
        all_counts = np.swapaxes(all_counts,0,1)
        all_counts = np.swapaxes(all_counts,1,2)
        vals = call_sgc(stat, all_counts, use_genotypes)
        
        estimates = {}
        for v,ii in zip(vals, range(len(all_counts[0,0]))):
            cs = tuple(tuple(c) for c in all_counts[:,:,ii])
            estimates[cs] = v
        
        for b in bs:
            sums.setdefault(b,{})
            sums[b][stat] = 0
            for cs in stat_counts:
                sums[b][stat] += stat_counts[cs][b] * estimates[cs]            
    
    return sums
    


def get_H_statistics(genotypes, sample_ids, pop_file=None, pops=None, ac_filter=False, report=True):
    """
    Het values are not normalized by sequence length, would need to compute L from bed file.
    """
    
    if pop_file == None and pops == None:
        if report == True:
            print("No population file or population names given, assuming all samples as single pop."); sys.stdout.flush()
    elif pops == None:
        raise ValueError("pop_file given, but not population names..."); sys.stdout.flush()
    elif pop_file == None:
        raise ValueError("Population names given, but not pop_file..."); sys.stdout.flush()
    
    if pops == None:
        pops = ['ALL']
    
    if pop_file is not None:
        samples = pandas.read_csv(pop_file, sep='\t')
        populations = np.array(samples['pop'].value_counts().keys())
        samples.reset_index(drop=True, inplace=True)

        ### should use this above when counting two locus genotypes
        sample_ids_list = list(sample_ids)
        subpops = {
            # for each population, get the list of samples that belong to the population
            pop_iter: [sample_ids_list.index(ind) for ind in samples[samples['pop'] == pop_iter]['sample']] for pop_iter in pops
        }
        
        ac_subpop = genotypes.count_alleles_subpops(subpops)
    else:
        subpops = {
            pop_iter: list(range(len(sample_ids))) for pop_iter in pops
        }
        ac_subpop = genotypes.count_alleles_subpops(subpops)
    
    # ensure at least 2 allele counts per pop
    if ac_filter == True:
        min_ac_filter = [True]*len(ac_subpop)
        for pop in pops:
            min_ac_filter = np.logical_and(min_ac_filter, np.sum(ac_subpop[pop], axis=1) >= 2)
        
        for pop in pops:
            ac_subpop[pop] = ac_subpop[pop].compress(min_ac_filter)
    
    Hs = {}
    for ii,pop1 in enumerate(pops):
        for pop2 in pops[ii:]:
            if pop1 == pop2:
                H = np.sum( 2. * ac_subpop[pop1][:,0] * ac_subpop[pop1][:,1] / (ac_subpop[pop1][:,0] + ac_subpop[pop1][:,1]) / (ac_subpop[pop1][:,0] + ac_subpop[pop1][:,1] - 1) )
            else:
                H = np.sum( 
                        1. * ac_subpop[pop1][:,0] * ac_subpop[pop2][:,1] / (ac_subpop[pop1][:,0] + ac_subpop[pop1][:,1]) / (ac_subpop[pop2][:,0] + ac_subpop[pop2][:,1]) 
                        + 1. * ac_subpop[pop1][:,1] * ac_subpop[pop2][:,0] / (ac_subpop[pop1][:,0] + ac_subpop[pop1][:,1]) / (ac_subpop[pop2][:,0] + ac_subpop[pop2][:,1]) 
                    )
            Hs[(pop1,pop2)] = H
    
    return Hs


def get_reported_stats(genotypes, bins, sample_ids, positions=None, pos_rs=None, pop_file=None, pops=None, use_genotypes=True, report=True, report_spacing=1000, use_cache=True, stats_to_compute=None, ac_filter=False):
    ### build wrapping function that can take use_cache = True or False
    # now if bins is empty, we only return heterozygosity statistics
    
    if stats_to_compute == None:
        if pops is None:
            stats_to_compute = Util.moment_names(1)
        else:
            stats_to_compute = Util.moment_names(len(pops))
    
    bs = list(zip(bins[:-1],bins[1:]))
    
    if use_cache == True:
        type_counts = count_types_sparse(genotypes, bins, sample_ids, positions=positions, pos_rs=pos_rs, pop_file=pop_file, pops=pops, use_genotypes=use_genotypes, report=report, report_spacing=report_spacing, use_cache=use_cache, ac_filter=ac_filter)
        
        #if report is True: print("counted genotypes"); sys.stdout.flush()
        #statistics_cache = cache_ld_statistics(type_counts, stats_to_compute[0], bins, use_genotypes=use_genotypes, report=report)
        #
        #if report is True: print("summing over genotype counts and statistics cache"); sys.stdout.flush()
        #sums = {}
        #for b in bs:
        #    sums[b] = {}
        #    for stat in stats_to_compute[0]:
        #        sums[b][stat] = 0
        #        for cs in type_counts[b]:
        #            sums[b][stat] += type_counts[b][cs] * statistics_cache[cs][stat]
        
        sums = get_ld_stat_sums(type_counts, stats_to_compute[0], bins, use_genotypes=use_genotypes, report=report)
        
    else:
        sums = count_types_sparse(genotypes, bins, sample_ids, positions=positions, pos_rs=pos_rs, pop_file=pop_file, pops=pops, use_genotypes=use_genotypes, report=report, report_spacing=report_spacing, use_cache=use_cache, stats_to_compute=stats_to_compute, ac_filter=ac_filter)
    
    if report is True: print("computed sums\ngetting heterozygosity statistics"); sys.stdout.flush()
        
    if len(stats_to_compute[1]) == 0:
        Hs = {}
    else:
        Hs = get_H_statistics(genotypes, sample_ids, pop_file=pop_file, pops=pops, ac_filter=ac_filter, report=report)
    
    reported_stats = {}
    reported_stats['bins'] = bs
    reported_stats['sums'] = [np.empty(len(stats_to_compute[0])) for b in bs] + [np.empty(len(stats_to_compute[1]))]
    for ii,b in enumerate(bs):
        for s in stats_to_compute[0]:
            reported_stats['sums'][ii][stats_to_compute[0].index(s)] = sums[b][s]
    
    if pops == None:
        pops = ['ALL']
    for s in stats_to_compute[1]:
        reported_stats['sums'][-1][stats_to_compute[1].index(s)] = Hs[(pops[int(s.split('_')[1])-1],pops[int(s.split('_')[2])-1])]
    reported_stats['stats'] = stats_to_compute
    reported_stats['pops'] = pops
    return reported_stats


def compute_ld_statistics(vcf_file, bed_file=None, chromosome=None, rec_map_file=None, map_name=None, map_sep='\t', pop_file=None, pops=None, cM=True, r_bins=None, bp_bins=None, min_bp=None, use_genotypes=True, use_h5=True, stats_to_compute=None, ac_filter=False, report=True, report_spacing=1000, use_cache=True):
    """
    vcf_file : path to vcf file
    bed_file : path to bed file to specify regions over which to compute LD statistics. If None, computes statistics
               for all positions in vcf_file
    rec_map_file : path to recombination map
    map_name : if None, takes the first map column, otherwise takes the specified map column
    map_sep : tells pandas how to parse the recombination map. Default is tabs, though I've been working 
              with space delimitted map files
    pop_file : 
    pops : 
    cM : 
    r_bins : 
    bp_bins : 
    min_bp : 
    use_genotypes : 
    use_h5 : 
    stats_to_compute : 
    report : 
    report_spacing : 
    use_cache : 
    
    Recombination map has the format XXX
    pop_file has the format XXX
    """
    
    check_imports()
    
    positions, genotypes, counts, sample_ids = get_genotypes(vcf_file, bed_file=bed_file, chromosome=chromosome, min_bp=min_bp, use_h5=use_h5, report=report)
    
    if report == True:
        print("kept {0} total variants".format(len(positions))); sys.stdout.flush()
    
    if rec_map_file is not None and r_bins is not None:
        if report is True: 
            print("assigning recombination rates to positions"); sys.stdout.flush()
        pos_rs = assign_recombination_rates(positions, rec_map_file, map_name=map_name, map_sep=map_sep, cM=cM, report=report)
        bins = r_bins
    else:
        if report is True:
            print("no recombination map provided, using physical distance"); sys.stdout.flush()
        pos_rs = None
        if bp_bins is not None:
            bins = bp_bins
        else:
            bins = []
    
    reported_stats = get_reported_stats(genotypes, bins, sample_ids, positions=positions, pos_rs=pos_rs, pop_file=pop_file, pops=pops, use_genotypes=use_genotypes, report=report, stats_to_compute=stats_to_compute, report_spacing=report_spacing, use_cache=use_cache, ac_filter=ac_filter)
    
    return reported_stats

def bootstrap_data(all_data, normalization=['pi2_1_1_1_1','H_1_1']):
    """
    all_data : dictionary (with arbitrary keys), where each value is are ld statistics computed
               from a distinct region. all_data[reg]
               stats from each region has keys, 'bins', 'sums', 'stats', and optional 'pops' (anything else?)
    normalization : we work with sigma_d^2 statistics, and by default we use population 1 to normalize stats
    
    We first check that all 'stats', 'bins', 'pops' (if present), match across all regions
    
    If there are N total regions, we compute N bootstrap replicates by sampling N times with replacement
        and summing over all 'sums'.
    """
    
    ## Check consistencies of bins, stats, and data sizes
    
    
    
    regions = list(all_data.keys())
    reg = regions[0]
    stats = all_data[reg]['stats']
    N = len(regions)
    
    # get means
    means = [0*sums for sums in all_data[reg]['sums']]
    for reg in regions:
        for ii in range(len(means)):
            means[ii] += all_data[reg]['sums'][ii]
    
    for ii in range(len(means)-1):
        means[ii] /= means[ii][stats[0].index(normalization[0])]
    means[-1] /= means[-1][stats[1].index(normalization[1])]
    
    
    # construct bootstrap data
    bootstrap_data = [np.zeros((len(sums),N)) for sums in means] 
    
    for boot_num in range(N):
        boot_means = [0*sums for sums in means]
        samples = np.random.choice(regions, N)
        for reg in samples:
            for ii in range(len(boot_means)):
                boot_means[ii] += all_data[reg]['sums'][ii]
        
        for ii in range(len(boot_means)-1):
            boot_means[ii] /= boot_means[ii][stats[0].index(normalization[0])]
        boot_means[-1] /= boot_means[-1][stats[1].index(normalization[1])]
        
        for ii in range(len(boot_means)):
            bootstrap_data[ii][:,boot_num] = boot_means[ii]

    varcovs = [np.cov(bootstrap_data[ii]) for ii in range(len(bootstrap_data))]

    mv = {}
    mv['bins'] = all_data[reg]['bins']
    mv['stats'] = all_data[reg]['stats']
    if 'pops' in all_data[reg]:
        mv['pops'] = all_data[reg]['pops']
    mv['means'] = means
    mv['varcovs'] = varcovs
    
    return mv



def subset_data(data, pops_to, normalization=1, r_min=None, r_max=None, remove_Dz=False):
    """
    to take the pickled data output by ... and get r_edges, ms, vcs, and stats 
        to pass to inference machinery
    Notes: Up to user to make sure that the order is preserved 
        (have a catch in future)
    """
    pops_from = data['pops']
    if np.all([p in pops_from for p in pops_to]) == False:
        raise ValueError("All pops in pops_to must be in data")
    
    new_pop_ids = {}
    for pop in pops_to:
        new_pop_ids[pops_from.index(pop)+1] = pops_to.index(pop)+1
    
    stats = data['stats']
    
    to_remove = [[],[]]
    new_stats = [[],[]]
    
    for j in [0,1]:
        for i,stat in enumerate(stats[j]):
            if stat in ['pi2_{0}_{0}_{0}_{0}'.format(normalization), 
                        'H_{0}_{0}'.format(normalization)]:
                to_remove[j].append(i)
            else:
                if remove_Dz == True:
                    if stat.split('_')[0] == 'Dz':
                        to_remove[j].append(i)
                        continue
                p_inds = [int(x) for x in stat.split('_')[1:]]
                if len(set(p_inds) - set(new_pop_ids)) == 0:
                    new_stat = '_'.join([stat.split('_')[0]] + 
                        [str(new_pop_ids[x]) for x in p_inds])
                    new_stats[j].append(new_stat)
                else:
                    to_remove[j].append(i)
    
    
    means = []
    varcovs = []
    
    for i,b in enumerate(data['bins']):
        if r_min is not None:
            if b[0] < r_min:
                continue
        if r_max is not None:
            if b[1] > r_max:
                continue
        means.append(np.delete(data['means'][i], to_remove[0]))
        varcovs.append(np.delete(np.delete(data['varcovs'][0], to_remove[0], axis=0), to_remove[0], axis=1))
    
    means.append(np.delete(data['means'][-1], to_remove[1]))
    varcovs.append(np.delete(np.delete(data['varcovs'][-1], to_remove[1], axis=0), to_remove[1], axis=1))
            
    r_edges = np.array(sorted(list(set( np.array(data['bins']).flatten() ))))
    if r_min is not None:
        r_edges = r_edges[r_edges >= r_min]
    if r_max is not None:
        r_edges = r_edges[r_edges <= r_max]
    
    return r_edges, means, varcovs, new_stats








