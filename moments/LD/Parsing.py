imported_h5py = 0
imported_allel = 0
try:
    import allel
    imported_allel = 1
except ImportError:
    pass

try:
    import h5py
    imported_h5py = 1
except ImportError:
    pass

import Util

def check_imports():
    if imported_allel == 0:
        raise("Failed to import allel package needed for Parsing. Is it installed?")
    if imported_h5py == 0:
        raise("Failed to import h5py package needed for Parsing. Is it installed?")

# later go through and trim the unneeded ones
import numpy as np
import pandas
from collections import Counter
import stats_from_genotype_counts as sgc

### right now can only handle one chromosome at a time !!!

def get_genotypes(vcf_file, bed_file=None, min_bp=None, use_h5=True):
    """
    Given a vcf file, we extract the biallelic SNP genotypes.
    If bed_file is None, we use all valid variants. Otherwise we filter genotypes
        by the given bed file.
        Warning!!! make sure that the chromosome labels are consistent (e.g., chr22 vs 22)
    If use_h5 is True, we try to load the h5 file, which has the same path/name as 
        vcf_file, but with *.h5 instead of *.vcf or *.vcf.gz. If the h5 file does not
        exist, we create it and save it as *.h5
    
    I strongly suggest using h5!! In fact, I haven't implemented use_h5=False yet,
        because I never use that option :)
    
    
    This function 
    """
    
    if use_h5 is True:
        ## open the h5 callset
        h5_file_path = vcf_file.split('.vcf')[0] + '.h5' # kinda hacky, sure
        try:
            callset = h5py.File(h5_file_path, mode='r')
        except OSError:
            print("need to create h5 file")
            allel.vcf_to_hdf5(vcf_file, h5_file_path, fields='*', overwrite=True)
            callset = h5py.File(h5_file_path, mode='r')
    else:
        ## read the vcf directly
        raise ValueError("Try using hdf5 format.")
    
    all_genotypes = allel.GenotypeChunkedArray(callset['calldata/GT'])
    all_positions = callset['variants/POS'][:]
    
    print("loaded genotypes")
    
    # filter SNPs not in bed file, if one is given
    if bed_file != None: # filter genotypes and positions
        mask_bed = pandas.read_csv(bed_file, sep='\t', header=None)
        chroms = ['chr'+c for c in list(set(callset['variants/CHROM'][:]))]
        
        chrom_filter = [False] * len(mask_bed)
        for chrom in chroms:
            chrom_filter = np.logical_or(chrom_filter, mask_bed[0] == chrom)
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
        print("created bed filter")
        
        all_positions = all_positions.compress(in_mask)
        all_genotypes = all_genotypes.compress(in_mask)
        
        print("filtered by bed")
    
    all_genotypes_012 = all_genotypes.to_n_alt(fill=-1)
    
    # count alleles and only keep biallelic positions
    allele_counts = all_genotypes.count_alleles()
    is_biallelic = allele_counts.is_biallelic_01()
    biallelic_positions = all_positions.compress(is_biallelic)
    biallelic_genotypes_012 = all_genotypes_012.compress(is_biallelic)
    biallelic_allele_counts = allele_counts.compress(is_biallelic)
    biallelic_genotypes = all_genotypes.compress(is_biallelic)
    
    print("kept biallelic positions")
    
    relevant_column = np.array([False] * biallelic_allele_counts.shape[1])
    relevant_column[0:2] = True
    biallelic_allele_counts = biallelic_allele_counts.compress(relevant_column, axis = 1)
    
    sample_ids = callset['samples']
    
    return biallelic_positions, biallelic_genotypes, biallelic_allele_counts, sample_ids
    

def assign_r_pos(positions, rec_map):
    rs = np.zeros(len(positions))
    for ii,pos in enumerate(positions):
        map_ii = np.where(pos >= np.array(rec_map[0]))[0][-1]
        l = rec_map[0][map_ii]
        r = rec_map[0][map_ii+1]
        v_l = rec_map[1][map_ii]
        v_r = rec_map[1][map_ii+1]
        rs[ii] = v_l + (v_r-v_l) * (pos-l)/(r-l)
    return rs


def assign_recombination_rates(positions, map_file, map_name=None, map_sep='\t', cM=True):
    if map_file == None:
        raise ValueError("Need to pass a recombination map file. Otherwise can bin by physical distance.")
    try:
        map = pandas.read_csv(map_file, sep=map_sep)
    except:
        raise ValueError("Error loading map.")
    
    if map_name == None: # we use the first map column
        print("No recombination map name given, using first column.")
    else:
        map_positions = map[map.keys()[0]]
        try:
            map_values = map[map_name]
        except KeyError:
            map_values = map[map.keys()[1]]
        
    # for positions sticking out the end of the map, they take the value of the closest position
    # ideally, you'd filter these out
    
    if cM == True:
        map_values /= 100
    
    pos_rs = assign_r_pos(positions, [map_positions, map_values])
    
    return pos_rs


def g_tally_counter(g_l, g_r):
    gs = list(zip(g_l,g_r))
    c = Counter(gs)
    return (c[(2,2)], c[(2,1)], c[(2,0)], 
            c[(1,2)], c[(1,1)], c[(1,0)], 
            c[(0,2)], c[(0,1)], c[(0,0)])


def count_genotypes(genotypes, bins, sample_ids, positions=None, pos_rs=None, pop_file=None, pops=None, report=10000):
    """
    genotypes : in format of 0,1,2
    """
    
    samples = pandas.read_csv(pop_file, sep='\t')
    
    pop_indexes = {}
    if pops is not None:
        cols_to_keep = np.array([False]*np.shape(genotypes)[1])
        all_samples_to_keep = []
        for pop in pops:
            all_samples_to_keep += list(samples[samples['pop'] == pop]['sample'])
        
        
        for s in all_samples_to_keep:
            cols_to_keep[list(sample_ids.value).index(s)] = True
        
        genotypes_pops = genotypes.compress(cols_to_keep, axis=1)
        allele_counts_pops = genotypes_pops.count_alleles()
        is_biallelic = allele_counts_pops.is_biallelic_01()
        genotypes_pops = genotypes_pops.compress(is_biallelic)
        
        sample_ids_pops = list(np.array(list(samples['sample'])).compress(cols_to_keep))
        
        for pop in pops:
            pop_indexes[pop] = np.array([False]*np.shape(genotypes_pops)[1])
            for s in samples[samples['pop'] == pop]['sample']:
                pop_indexes[pop][sample_ids_pops.index(s)] = True
        
        if positions is not None:
            positions = positions.compress(is_biallelic)
        if pos_rs is not None:
            pos_rs = pos_rs.compress(is_biallelic)
        
    else:
        print("No populations given, using all samples as one population.")
        pops = ['ALL']
        pop_indexes['ALL'] = np.array([True]*len(np.shape(genotypes)[1]))
        genotypes_pops = genotypes
    
    genotypes_pops_012 = genotypes_pops.to_n_alt()
    
    ## only keep biallelic positions that are variable in the populations we care about
    
    bs = list(zip(bins[:-1],bins[1:]))
    
    genotype_counts = {}
    for b in bs:
        genotype_counts[b] = {}
    
    if pos_rs is not None:
        rs = pos_rs
    elif positions is not None:
        rs = positions
    
    ns = np.array([2 * sum(pop_indexes[pop]) for pop in pops])
    
    for ii,r in enumerate(rs):
        if ii%report == 0:
            print("tallied two locus genotype counts {0} of {1} positions".format(ii, len(rs)))
        
## delete
        if ii >= 1000:
            break
        
        gs_ii = genotypes_pops_012[ii]
        gs_l = [gs_ii.compress(pop_indexes[pop]) for pop in pops]
        
        allele_counts = np.array([sum(g_l) for g_l in gs_l])
        
        if np.all(allele_counts == np.array([0]*len(pops))) or np.all(allele_counts == ns):
            continue
        
        for b in bs:
            filt = np.logical_and(pos_rs[ii:] - r >= b[0], pos_rs[ii:] - r < b[1])
            gs_to_right = genotypes_pops_012[ii:].compress(filt, axis=0)
            if np.shape(gs_to_right) is ():
                continue
            for gs_jj in gs_to_right:
                gs_r = [gs_jj.compress(pop_indexes[pop]) for pop in pops]
                cs = tuple([g_tally_counter(gl, gr) for gr,gl in zip(gs_l, gs_r)])
                genotype_counts[b].setdefault(cs,0)
                genotype_counts[b][cs] += 1
    
    return genotype_counts


def call_sgc(stat, Gs):
    s = stat.split('_')[0]
    pops = [int(p)-1 for p in stat.split('_')[1:]]
    if s == 'DD':
        return sgc.DD(Gs, pops)
    if s == 'Dz':
        return sgc.Dz(Gs, pops)
    if s == 'pi2':
        return sgc.pi2(Gs, pops)


def cache_ld_statistics(genotype_counts, ld_stats, bins):
    bs = list(zip(bins[:-1],bins[1:]))
    
    estimates = {}
    for b in bs:
        for cs in genotype_counts[b].keys():
            estimates.setdefault(cs, {})
    
    all_counts = np.array(list(estimates.keys()))
    all_counts = np.swapaxes(all_counts,0,1)
    all_counts = np.swapaxes(all_counts,1,2)
    
    for stat in ld_stats:
        print("computing " + stat)
        vals = call_sgc(stat, all_counts)
        for ii in range(len(all_counts[0,0])):
            cs = all_counts[:,:,ii]
            estimates[tuple([tuple(c) for c in cs])][stat] = vals[ii]
    return estimates


def get_H_statistics(genotypes, sample_ids, pop_file=None, pops=None):
    """
    H values are not normalized by sequence length, would need to compute L from bed file.
    """
    samples = pandas.read_csv(pop_file, sep='\t')

    populations = np.array(samples['pop'].value_counts().keys())

    samples.reset_index(drop=True, inplace=True)

### should use this above when counting two locus genotypes

    subpops = {
        # for each population, get the list of samples that belong to the population
        pop_iter: samples[samples['pop'] == pop_iter].index.tolist() for pop_iter in pops
    }


    ac_subpop = genotypes.count_alleles_subpops(subpops)

#L = 0
#for l,r in zip(mask_bed[1], mask_bed[2]):
#    L += r-l

    Hs = {}
    for ii,pop1 in enumerate(list(subpops.keys())):
        for pop2 in list(subpops.keys())[ii:]:
            if pop1 == pop2:
                H = np.sum( 2. * ac_subpop[pop1][:,0] * ac_subpop[pop1][:,1] / (ac_subpop[pop1][:,0] + ac_subpop[pop1][:,1]) / (ac_subpop[pop1][:,0] + ac_subpop[pop1][:,1] - 1) )
            else:
                H = np.sum( ac_subpop[pop1][:,0] * ac_subpop[pop2][:,1] / (ac_subpop[pop1][:,0] + ac_subpop[pop1][:,1]) / (ac_subpop[pop2][:,0] + ac_subpop[pop2][:,1]) + ac_subpop[pop1][:,1] * ac_subpop[pop2][:,0] / (ac_subpop[pop1][:,0] + ac_subpop[pop1][:,1]) / (ac_subpop[pop2][:,0] + ac_subpop[pop2][:,1]) )
            Hs[(pop1,pop2)] = H
    
    return Hs


def compute_ld_statistics(vcf_file, bed_file=None, rec_map_file=None, map_name=None, map_sep='\t', pop_file=None, pops=None, r_bins=None, bp_bins=None, min_bp=None, use_h5=True):

    """ testing
    vcf_file = '/Users/aragsdal/Data/Human/ThousandGenomes/genotypes/ALL.chr22.phase3_shapeit2_mvncall_integrated_v5a.20130502.genotypes.vcf.gz'
    bed_file = '/Users/aragsdal/Data/Human/ThousandGenomes/masks/gencode_v19_intergenic_strict_mask.flank20k.chr22.bed.gz'
    rec_map_file = '/Users/aragsdal/Data/Human/maps_b37/maps_chr.22'
    pop_file = '/Users/aragsdal/Data/Human/ThousandGenomes/genotypes/integrated_call_samples_v3.20130502.ALL.panel'
    pops = ['YRI','CEU','CHB']
    
    min_bp = 100
    use_h5 = True
    
    map_name = 'AA_Map'
    map_sep = ' '
    
    r_bins = [0.00001, 0.00005, 0.0001, 0.0005, 0.001, 0.002]
    
    """
    
    positions, genotypes, counts, sample_ids = get_genotypes(vcf_file, bed_file=bed_file, min_bp=min_bp, use_h5=use_h5)
    
    if rec_map_file is not None and r_bins is not None:
        pos_rs = assign_recombination_rates(positions, rec_map_file, map_name=map_name, map_sep=map_sep)
        bins = r_bins
    else:
        if bp_bins is not None:
            bins = bp_bins
        else:
            bins = []
    
    # now if bins is empty, we only return heterozygosity statistics
    
    genotype_counts = count_genotypes(genotypes, bins, sample_ids, positions=None, pos_rs=pos_rs, pop_file=pop_file, pops=pops, report=100)
    
#    if pops is None:
#        stats_to_compute = Util.moment_names(1)
#    else:
#        stats_to_compute = Util.moment_names(len(pops))
    stats_to_compute = (['DD_1_1','DD_1_2','DD_1_3','DD_2_2','DD_2_3','DD_3_3','pi2_1_1_1_1'],['H_1_1', 'H_1_2', 'H_1_3', 'H_2_2', 'H_2_3', 'H_3_3'])
    
    
    statistics_cache = cache_ld_statistics(genotype_counts, stats_to_compute[0], bins)
    
    bs = list(zip(bins[:-1],bins[1:]))
    sums = {}
    for b in bs:
        sums[b] = {}
        for stat in stats_to_compute[0]:
            sums[b][stat] = 0
            for cs in genotype_counts[b]:
                sums[b][stat] += genotype_counts[b][cs] * estimates[cs][stat]
    
    Hs = get_H_statistics(genotypes, sample_ids, pop_file=None, pops=None)
    
    

def bootstrap_data():
    pass
