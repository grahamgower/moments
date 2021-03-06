"""
Contains two locus spectrum object
"""
import logging
logging.basicConfig()
logger = logging.getLogger('TLSpectrum_mod')

import os
import numpy, numpy as np
import moments.TwoLocus.Numerics
import moments.TwoLocus.Integration
import scipy.special

class TLSpectrum(numpy.ma.masked_array):
    """
    Represents a two locus frequency spectrum.
    
    Spectra are represented ...
    
    The constructor has the format:
        fs = moments.TwoLocus.TLSpectrum(data, mask, mask_infeasible, mask_fixed,
                                data_folded)
        
        data: The frequency spectrum data
        mask: An optional array of the same size as data. 'True' entries in this array
              are masked in the TLSpectrum. These represent missing data categories,
              or invalid entries in the array.
        data_folded: If True, it is assumed that the input data is folded 
                     for the major and minor derived alleles
        check_folding: If True and data_folded_ancestral=True, the data and
                       mask will be checked to ensure they are consistent
    """
    def __new__(subtype, data, mask=numpy.ma.nomask, mask_infeasible=True,
                mask_fixed=False,
                data_folded=None, check_folding=True,
                dtype=float, copy=True, fill_value=numpy.nan, keep_mask=True,
                shrink=True):
        data = numpy.asanyarray(data)
        
        if mask is numpy.ma.nomask:
            mask = numpy.ma.make_mask_none(data.shape)
        
        subarr = numpy.ma.masked_array(data, mask=mask, dtype=dtype, copy=copy,
                                       fill_value=fill_value, keep_mask=True, 
                                       shrink=True)
        subarr = subarr.view(subtype)
        if hasattr(data, 'folded'):
            if data_folded is None or data_folded == data.folded:
                subarr.folded = data.folded
            elif data_folded != data.folded:
                raise ValueError('Data does not have same folding status as '
                                 'was called for in Spectrum constructor.')
        elif data_folded is not None:
            subarr.folded = data_folded
        else:
            subarr.folded = False
                
        if mask_infeasible:
            subarr.mask_infeasible()
        
        if mask_fixed:
            subarr.mask_fixed()
        
        return subarr
    
    def __array_finalize__(self, obj):
        if obj is None: 
            return
        np.ma.masked_array.__array_finalize__(self, obj)
        self.folded = getattr(obj, 'folded', 'unspecified')
    def __array_wrap__(self, obj, context=None):
        result = obj.view(type(self))
        result = np.ma.masked_array.__array_wrap__(self, obj, 
                                                      context=context)
        result.folded = self.folded
        return result
    def _update_from(self, obj):
        np.ma.masked_array._update_from(self, obj)
        if hasattr(obj, 'folded'):
            self.folded = obj.folded
    # masked_array has priority 15.
    __array_priority__ = 20
    
    def __repr__(self):
        return 'TLSpectrum(%s, folded=%s)'\
                % (str(self), str(self.folded))

    def mask_infeasible(self):
        """
        Mask any infeasible entries.
        """
        ns = len(self)-1
        # mask entries with i+j+k > ns
        for ii in range(len(self)):
            for jj in range(len(self)):
                for kk in range(len(self)):
                    if ii+jj+kk > ns:
                        self.mask[ii,jj,kk] = True
                
        return self
    
    def mask_fixed(self):
        """
        Mask all infeasible, as well as any where both sites are not segregating
        """
        ns = len(self)-1
        # mask fixed entries
        self.mask[0,0,0] = True
        self.mask[0,0,-1] = True
        self.mask[0,-1,0] = True
        self.mask[-1,0,0] = True
        # mask entries with i+j+k > ns
        for ii in range(len(self)):
            for jj in range(len(self)):
                for kk in range(len(self)):
                    if ii+jj+kk > ns:
                        self.mask[ii,jj,kk] = True
        
        # mask fA = 0 and fB = 0
        for ii in range(len(self)):
            self.mask[ii,ns-ii,0] = True
            self.mask[ii,0,ns-ii] = True

        self.mask[0,:,0] = True
        self.mask[0,0,:] = True
        return self
    
    def unfold(self):
        if not self.folded:
            raise ValueError('Input Spectrum is not folded.')
        data = self.data
        unfolded = TLSpectrum(data, mask_infeasible=True)
        return unfolded

    def _get_sample_size(self):
        return np.asarray(self.shape)[0] - 1
    sample_size = property(_get_sample_size)
    
    def left(self):
        """
        The marginal allele frequency spectrum at the left locus
        index in new AFS is ii+jj
        """
        n = len(self)-1
        fl = np.zeros(n+1)
        for ii in range(n+1):
            for jj in range(n+1-ii):
                for kk in range(n+1-ii-jj):
                    fl[ii+jj] += self[ii,jj,kk]
        return fl
    
    def right(self):
        """
        The marginal AFS at the right locus
        """
        n = len(self)-1
        fr = np.zeros(n+1)
        for ii in range(n+1):
            for jj in range(n+1-ii):
                for kk in range(n+1-ii-jj):
                    fr[ii+kk] += self[ii,jj,kk]
        return fr
    
    def D(self, proj=True):
        n = len(self)-1
        DD = 0
        for ii in range(n+1):
            for jj in range(n+1-ii):
                for kk in range(n+1-ii-jj):
                    if self.mask[ii,jj,kk] == True:
                        continue
                    if ii+jj == 0 or ii+kk == 0 or ii+jj == n or ii+kk == n:
                        continue
                    else:
                        if proj == True:
                            DD += self.data[ii,jj,kk] * ( ii*(n-ii-jj-kk)/float(n*(n-1)) - jj*kk/float(n*(n-1)) )
                        else:
                            DD += self.data[ii,jj,kk] * ( ii*(n-ii-jj-kk)/float(n**2) - jj*kk/float(n**2) )
        return DD
        
    def D2(self, proj=True):
        n = len(self)-1
        DD2 = 0
        for ii in range(n+1):
            for jj in range(n+1-ii):
                for kk in range(n+1-ii-jj):
                    if self.mask[ii,jj,kk] == True:
                        continue
                    if ii+jj == 0 or ii+kk == 0 or ii+jj == n or ii+kk == n:
                        continue
                    else:
                        if proj == True:
                            DD2 += self.data[ii,jj,kk] * 1./3 * ( scipy.special.binom(ii,2)*scipy.special.binom(n-ii-jj-kk,2)/scipy.special.binom(n,4) + scipy.special.binom(jj,2)*scipy.special.binom(kk,2)/scipy.special.binom(n,4) - 1./2 * ii*jj*kk*(n-ii-jj-kk)/scipy.special.binom(n,4) )
                        else:
                            DD2 += self.data[ii,jj,kk] * 2./n**4 * ( ii**2 * (n-ii-jj-kk)**2 + jj**2 * kk**2 - 2*ii * jj * kk * (n-ii-jj-kk) )
        return DD2

    def pi2(self, proj=True):
        n = len(self)-1
        stat = 0
        for ii in range(n+1):
            for jj in range(n+1-ii):
                for kk in range(n+1-ii-jj):
                    if self.mask[ii,jj,kk] == True:
                        continue
                    ll = n-ii-jj-kk
                    if ii+jj == 0 or ii+kk == 0 or ii+jj == n or ii+kk == n:
                        continue
                    else:
                        if proj == True:
                            stat += self.data[ii,jj,kk] * 2./scipy.special.binom(n,4) * (
                                        ii*(ii-1)/2*jj*kk / 12. + 
                                        ii*jj*(jj-1)/2*kk / 12. + 
                                        ii*jj*kk*(kk-1)/2 / 12. + 
                                        jj*(jj-1)/2*kk*(kk-1)/2 / 6. + 
                                        ii*(ii-1)/2*jj*ll / 12. + 
                                        ii*jj*(jj-1)/2*ll / 12. + 
                                        ii*(ii-1)/2*kk*ll / 12. + 
                                        2 * ii*jj*kk*ll / 24. + 
                                        jj*(jj-1)/2*kk*ll / 12. + 
                                        ii*kk*(kk-1)/2*ll / 12. + 
                                        jj*kk*(kk-1)/2*ll / 12. + 
                                        ii*(ii-1)/2*ll*(ll-1)/2 / 6. + 
                                        ii*jj*ll*(ll-1)/2 / 12. + 
                                        ii*kk*ll*(ll-1)/2 / 12. + 
                                        jj*kk*ll*(ll-1)/2 / 12.
                                        )
                        else:
                            stat += self.data[ii,jj,kk] * 2./n**4 * (
                                        ii**2*jj*kk + 
                                        ii*jj**2*kk + 
                                        ii*jj*kk**2 + 
                                        jj**2*kk**2 + 
                                        ii**2*jj*ll + 
                                        ii*jj**2*ll + 
                                        ii**2*kk*ll + 
                                        2 * ii*jj*kk*ll + 
                                        jj**2*kk*ll + 
                                        ii*kk**2*ll + 
                                        jj*kk**2*ll + 
                                        ii**2*ll**2 + 
                                        ii*jj*ll**2 + 
                                        ii*kk*ll**2 + 
                                        jj*kk*ll**2
                                        )
        return stat
    
    def Dz(self, proj=True):
        n = len(self)-1
        if proj == False:
            print("not implemented with proj=False")
            return
        else:
            F_proj = self.project(4)
            stat = 1./4*F_proj[3,0,0] - 1./3*F_proj[2,0,0] + 1./4*F_proj[1,0,0] - 1./12*F_proj[2,1,1] - 1./12*F_proj[1,2,0] - 1./12*F_proj[1,0,2] - 1./12*F_proj[0,1,1] + 1./4*F_proj[0,3,1] - 1./3*F_proj[0,2,2] + 1./4*F_proj[0,1,3] + 1./6*F_proj[1,1,1]
            return 2*stat
    
# Make from_file a static method, so we can use it without an instance.
    @staticmethod
    def from_file(fid, mask_infeasible=True, return_comments=False):
        """
        Read frequency spectrum from file.

        fid: string with file name to read from or an open file object.
        mask_infeasible: If True, mask the infeasible entries in the two locus spectrum.
        return_comments: If true, the return value is (fs, comments), where
                         comments is a list of strings containing the comments
                         from the file (without #'s).

        See to_file method for details on the file format.
        """
        newfile = False
        # Try to read from fid. If we can't, assume it's something that we can
        # use to open a file.
        if not hasattr(fid, 'read'):
            newfile = True
            fid = open(fid, 'r')

        line = fid.readline()
        # Strip out the comments
        comments = []
        while line.startswith('#'):
            comments.append(line[1:].strip())
            line = fid.readline()

        # Read the shape of the data
        shape,folded = line.split()
        shape = [int(shape)+1,int(shape)+1,int(shape)+1]

        data = np.fromstring(fid.readline().strip(), 
                                count=np.product(shape), sep=' ')
        # fromfile returns a 1-d array. Reshape it to the proper form.
        data = data.reshape(*shape)

        maskline = fid.readline().strip()
        mask = np.fromstring(maskline, 
                                count=np.product(shape), sep=' ')
        mask = mask.reshape(*shape)
        
        if folded == 'folded':
            folded = True
        else:
            folded = False

        # If we opened a new file, clean it up.
        if newfile:
            fid.close()

        fs = TLSpectrum(data, mask, mask_infeasible, data_folded=folded)
        if not return_comments:
            return fs
        else:
            return fs,comments
    
    def to_file(self, fid, precision=16, comment_lines=[], foldmaskinfo=True):
        """
        Write frequency spectrum to file.
    
        fid: string with file name to write to or an open file object.
        precision: precision with which to write out entries of the SFS. (They 
                   are formated via %.<p>g, where <p> is the precision.)
        comment lines: list of strings to be used as comment lines in the header
                       of the output file.
        foldmaskinfo: If False, folding and mask and population label
                      information will not be saved.

        The file format is:
            # Any number of comment lines beginning with a '#'
            A single line containing N integers giving the dimensions of the fs
              array. So this line would be '5 5 3' for an SFS that was 5x5x3.
              (That would be 4x4x2 *samples*.)
            On the *same line*, the string 'folded' or 'unfolded' 
              denoting the folding status of the array
            A single line giving the array elements. The order of elements is 
              e.g.: fs[0,0,0] fs[0,0,1] fs[0,0,2] ... fs[0,1,0] fs[0,1,1] ...
            A single line giving the elements of the mask in the same order as
              the data line. '1' indicates masked, '0' indicates unmasked.
        """
        # Open the file object.
        newfile = False
        if not hasattr(fid, 'write'):
            newfile = True
            fid = open(fid, 'w')

        # Write comments
        for line in comment_lines:
            fid.write('# ')
            fid.write(line.strip())
            fid.write(os.linesep)

        # Write out the shape of the fs
        fid.write('{0} '.format(self.sample_size))

        if foldmaskinfo:
            if not self.folded:
                fid.write('unfolded ')
            else:
                fid.write('folded ')
        
        fid.write(os.linesep)

        # Write the data to the file
        self.data.tofile(fid, ' ', '%%.%ig' % precision)
        fid.write(os.linesep)

        if foldmaskinfo:
            # Write the mask to the file
            np.asarray(self.mask,int).tofile(fid, ' ')
            fid.write(os.linesep)

        # Close file
        if newfile:
            fid.close()

    tofile = to_file
    
    def fold(self):
        if self.folded:
            raise ValueError('Input Spectrum is already folded.')
        ns = self.shape[0] - 1
        folded = 0*self
        for ii in range(ns+1):
            for jj in range(ns+1):
                for kk in range(ns+1):
                    if self.mask[ii,jj,kk]:
                        continue
                    p = ii + jj
                    q = ii + kk
                    if p > ns/2 and q > ns/2:
                        # Switch A/a and B/b, so AB becomes ab, Ab becomes aB, etc
                        folded[ns-ii-jj-kk,kk,jj] += self.data[ii,jj,kk]
                        folded.mask[ii,jj,kk] = True
                    elif p > ns/2:
                        # Switch A/a, so AB -> aB, Ab -> ab, aB -> AB, and ab -> Ab
                        folded[kk,ns-ii-jj-kk,ii] += self.data[ii,jj,kk]
                        folded.mask[ii,jj,kk] = True
                    elif q > ns/2:
                        # Switch B/b, so AB -> Ab, Ab -> AB, aB -> ab, and ab -> aB
                        folded[jj,ii,ns-ii-jj-kk] += self.data[ii,jj,kk]
                        folded.mask[ii,jj,kk] = True
                    else:
                        folded[ii,jj,kk] += self.data[ii,jj,kk]
        folded.folded = True
        return folded
    

    def project(self, ns, finite_genome=False):
        """
        Project to smaller sample size.
        ns: Sample size for new spectrum.
        """
        data = moments.TwoLocus.Numerics.project(self, ns)
        output = TLSpectrum(data, mask_infeasible=True)
        return output            
    
    # Ensures that when arithmetic is done with TLSpectrum objects,
    # attributes are preserved. For details, see similar code in
    # moments.Spectrum_mod
    for method in ['__add__','__radd__','__sub__','__rsub__','__mul__',
                   '__rmul__','__div__','__rdiv__','__truediv__','__rtruediv__',
                   '__floordiv__','__rfloordiv__','__rpow__','__pow__']:
        exec("""
def %(method)s(self, other):
    self._check_other_folding(other)
    if isinstance(other, np.ma.masked_array):
        newdata = self.data.%(method)s (other.data)
        newmask = np.ma.mask_or(self.mask, other.mask)
    else:
        newdata = self.data.%(method)s (other)
        newmask = self.mask
    outfs = self.__class__.__new__(self.__class__, newdata, newmask, 
                                   mask_infeasible=False, 
                                   data_folded=self.folded)
    return outfs
""" % {'method':method})

    # Methods that modify the Spectrum in-place.
    for method in ['__iadd__','__isub__','__imul__','__idiv__',
                   '__itruediv__','__ifloordiv__','__ipow__']:
        exec("""
def %(method)s(self, other):
    self._check_other_folding(other)
    if isinstance(other, np.ma.masked_array):
        self.data.%(method)s (other.data)
        self.mask = np.ma.mask_or(self.mask, other.mask)
    else:
        self.data.%(method)s (other)
    return self
""" % {'method':method})

    def _check_other_folding(self, other):
        """
        Ensure other Spectrum has same .folded status
        """
        if isinstance(other, self.__class__)\
           and (other.folded != self.folded):
            raise ValueError('Cannot operate with a folded Spectrum and an '
                             'unfolded one.')
    
    def integrate(self, nu, tf, dt=0.01, rho=None, gamma=None, h=None, sel_params=None, theta=1.0, finite_genome=False, u=None, v=None, alternate_fg=None):
        """
        Method to simulate the triallelic fs forward in time.
        This integration scheme takes advantage of scipy's sparse methods.
        nu: population effective sizes as positive value or callable function
        tf: integration time in genetics units
        dt_fac: time step for integration
        gammas: Population size scaled selection coefficients [sAA, sA0, sBB, sB0, sAB]
                See documentation for definition and use
        theta: Population size scale mutation parameter
        """
        if gamma == None:
            gamma = 0.0
        if h == None:
            h = 0.5
        if rho == None:
            rho = 0.0
            print('Warning: rho was not specified. Simulating with rho = 0.')
        
        self.data[:] = moments.TwoLocus.Integration.integrate(self.data, nu, tf, rho=rho, dt=dt, theta=theta,
                                    gamma=gamma, h=h, sel_params=sel_params,
                                    finite_genome=finite_genome, u=u, v=v,
                                    alternate_fg=alternate_fg)
        
        #return self # comment out (returned for testing earlier)

# Allow TLSpectrum objects to be pickled. 
# See http://effbot.org/librarybook/copy-reg.htm
try:
    import copy_reg
except:
    import copyreg
def TLSpectrum_pickler(fs):
    # Collect all the info necessary to save the state of a TLSpectrum
    return TLSpectrum_unpickler, (fs.data, fs.mask, fs.folded)
def TLSpectrum_unpickler(data, mask, folded):
    # Use that info to recreate the TLSpectrum
    return TLSpectrum(data, mask, mask_infeasible=False,
                       data_folded=folded)

try:
    copy_reg.pickle(TLSpectrum, TLSpectrum_pickler, TLSpectrum_unpickler)
except:
    copyreg.pickle(TLSpectrum, TLSpectrum_pickler, TLSpectrum_unpickler)
