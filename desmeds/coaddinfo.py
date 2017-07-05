from __future__ import print_function
import os
import shutil
import numpy
import fitsio
import tempfile
import subprocess

from . import files

class Coadd(object):
    """
    information for coadds.  Can use the download() method to copy
    to the local disk heirchy
    """
    def __init__(self, campaign='Y3A1_COADD', src=None, sources=None):
        self.campaign=campaign.upper()
        self._set_cache()
        self.sources=sources

    def get_info(self, tilename, band):
        """
        get info for the specified tilename and band

        if sources were sent to the constructor, add source info as well
        """
        info = self.cache.get_info(tilename, band)

        # add full path info
        self._add_full_paths(info)

        sources=self.get_sources()
        if sources is not None:
            self._add_src_info(info, tilename, band)

        return info

    def download(self, tilename, band):
        """
        download sources for a single tile and band
        """

        info_list=self.get_info(tilename,band)

        flist_file=self._write_download_flist(info_list)

        cmd=_DOWNLOAD_CMD % flist_file

        try:
            subprocess.check_call(cmd,shell=True)
        finally:
            files.try_remove(flist_file)

    def remove(self, tilename, band):
        """
        remove downloaded files for the specified tile and band
        """

        info=self.get_info(tilename,band)
        flist=self._get_download_flist(info)

        for fname in flist:
            if os.path.exists(fname):
                print("removing:",fname)
                files.try_remove(fname)

    def get_sources(self):
        """
        get the source list
        """
        return self.sources


    def _add_full_paths(self, info):
        """
        seg maps don't have .fz extension for coadd
        """
        dirdict=self._get_all_dirs(info)
        info['image_path'] = os.path.join(
            dirdict['image']['local_dir'],
            info['filename']+info['compression'],
        )
        info['cat_path'] = os.path.join(
            dirdict['cat']['local_dir'],
            info['filename'].replace('.fits','_cat.fits'),
        )
        info['seg_path'] = os.path.join(
            dirdict['seg']['local_dir'],
            info['filename'].replace('.fits','_segmap.fits'),
        )
        info['psf_path'] = os.path.join(
            dirdict['psf']['local_dir'],
            info['filename'].replace('.fits','_psfcat.psf'),
        )


    def _get_download_flist(self, info, no_prefix=False):
        """
        get list of files for this tile

        parameters
        ----------
        info: dict
            The info dict for this tile/band, possibly including
            the src_info

        no_prefix: bool 
            If True, the $DESDATA/ is removed from the front
        """
        desdata=files.get_desdata()

        if desdata[-1] != '/':
            desdata += '/'

        types=self._get_download_types()
        stypes=self._get_source_download_types()

        flist=[]
        for type in types:
            tname='%s_path' % type

            fname = info[tname]

            if no_prefix:
                fname = fname.replace(desdata, '')

            flist.append(fname)

        if 'src_info' in info:
            for sinfo in info['src_info']:
                for type in stypes:
                    tname='%s_path' % type

                    fname = sinfo[tname]

                    if no_prefix:
                        fname = fname.replace(desdata, '')

                    flist.append(fname)


        return flist


    def _write_download_flist(self, info):

        flist_file=self._get_tempfile()
        flist=self._get_download_flist(info, no_prefix=True)

        print("writing file list to:",flist_file)
        with open(flist_file,'w') as fobj:
            for fname in flist:
                fobj.write(fname)
                fobj.write('\n')

        return flist_file

    def _get_tempfile(self):
        return tempfile.mktemp(
            prefix='coadd-flist-',
            suffix='.dat',
        )


    def _get_download_types(self):
        return ['image','cat','seg','psf']

    def _get_source_download_types(self):
        return ['image','bkg','seg','psf','head']


    def _add_src_info(self, info, tilename, band):
        """
        get path info for the input single-epoch sources
        """

        sources=self.get_sources()
        src_info = self.sources.get_info(tilename, band=band)

        self._add_head_full_paths(info, src_info)

        info['src_info'] = src_info

    def _add_head_full_paths(self, info, src_info):
        dirdict=self._get_all_dirs(info)

        # this is a full path
        auxdir=dirdict['aux']['local_dir']

        head_front=info['filename'][0:-7]

        for src in src_info:
            fname=src['filename']

            fid = fname[0:15]

            head_fname = '%s_%s_scamp.ohead' % (head_front, fid)

            src['head_path'] = os.path.join(
                auxdir,
                head_fname,
            )




    def _set_cache(self):
        self.cache = CoaddCache(self.campaign)

    def _get_all_dirs(self, info):
        dirs={}

        path=info['path']
        dirs['image'] = self._get_dirs(path)
        dirs['cat'] = self._get_dirs(path, type='cat')
        dirs['aux'] = self._get_dirs(path, type='aux')
        dirs['seg'] = self._get_dirs(path, type='seg')
        dirs['psf'] = self._get_dirs(path, type='psf')
        return dirs

    def _get_dirs(self, path, type=None):
        local_dir = '$DESDATA/%s' % path
        remote_dir = '$DESREMOTE_RSYNC/%s' % path

        local_dir=os.path.expandvars(local_dir)
        remote_dir=os.path.expandvars(remote_dir)

        if type is not None:
            local_dir=self._extract_alt_dir(local_dir,type)
            remote_dir=self._extract_alt_dir(remote_dir,type)

        return {
            'local_dir':local_dir,
            'remote_dir':remote_dir,
        }

    def _extract_alt_dir(self, path, type):
        """
        extract the catalog path from an image path, e.g.

        OPS/multiepoch/Y3A1/r2577/DES0215-0458/p01/coadd/

        would yield

        OPS/multiepoch/Y3A1/r2577/DES0215-0458/p01/{type}/
        """

        ps = path.split('/')

        assert ps[-1]=='coadd'

        ps[-1] = type
        return '/'.join(ps)


class CoaddCache(object):
    """
    cache to hold path info for the coadds
    """
    def __init__(self, campaign='Y3A1_COADD'):
        self.campaign=campaign.upper()

    def get_data(self):
        """
        get the full cache data
        """
        if not hasattr(self,'_cache'):
            self.load_cache()

        return self._cache

    def get_info(self, tilename, band='i'):
        """
        get info for the specified tilename and band
        """


        cache = self.get_data()

        key = make_cache_key(tilename, band)
        w,=numpy.where(cache['key'] == key)
        if w.size == 0:
            raise ValueError("%s not found in cache" % key)

        c=cache[w[0]]

        tilename=c['tilename'].strip()
        path=c['path'].strip()
        filename=c['filename'].strip()
        band=c['band'].strip()
        comp=c['compression'].strip()

        entry = {
            'tilename':tilename,
            'filename':filename,
            'compression':comp,
            'path':path,
            'band':band,
            'pfw_attempt_id':c['pfw_attempt_id'],
        }

        return entry

    def load_cache(self):
        """
        load the cache into memory
        """

        fname=self.get_filename()
        if not os.path.join(fname):
            self.make_cache()

        print("loading cache:",fname)
        self._cache = fitsio.read(fname)

    def make_cache(self):
        """
        cache all the relevant information for this campaign
        """

        fname=self.get_filename()

        print("writing to:",fname)
        curs = self._doquery()

        dt=self._get_dtype()

        info=numpy.fromiter(curs, dtype=dt)


        print("writing to:",fname)
        fitsio.write(fname, info, clobber=True)

    def _get_dtype(self):
        return [ 
            ('key','S14'),
            ('tilename','S12'),
            ('path','S65'),
            ('filename','S40'),
            ('compression','S3'),
            ('band','S1'),
            ('pfw_attempt_id','i8'),

        ]

    def get_filename(self):
        """
        path to the cache
        """
        return files.get_coadd_cache_file(self.campaign)

    def _doquery(self):

        query = self._get_query()
        print(query)
        conn=self.get_conn()
        curs = conn.cursor()
        curs.execute(query)

        return curs

    def _get_query(self):
        query = _QUERY_COADD_TEMPLATE.format(
            campaign=self.campaign,
        )
        return query

    def get_conn(self):
        if not hasattr(self, '_conn'):
            self._make_conn()

        return self._conn

    def _make_conn(self):
        import easyaccess as ea
        self._conn=ea.connect(section='desoper')


def make_cache_key(tilename, band):
    return '%s-%s' % (tilename, band)



_QUERY_COADD_TEMPLATE="""
select
    m.tilename || '-' || m.band as key,
    m.tilename as tilename,
    fai.path as path,
    fai.filename as filename,
    fai.compression as compression,
    m.band as band,
    m.pfw_attempt_id as pfw_attempt_id

from
    prod.proctag t,
    prod.coadd m,
    prod.file_archive_info fai
where
    t.tag='{campaign}'
    and t.pfw_attempt_id=m.pfw_attempt_id
    and m.filetype='coadd'
    and fai.filename=m.filename
    and fai.archive_name='desar2home'\n"""

_DOWNLOAD_CMD = r"""
    rsync \
        -av \
        --password-file $DES_RSYNC_PASSFILE \
        --files-from=%s \
        ${DESREMOTE_RSYNC}/ \
        ${DESDATA}/ 
"""
_DOWNLOAD_AUX_CMD = r"""
    rsync \
        -av \
        --password-file $DES_RSYNC_PASSFILE \
        --files-from=%s \
        ${DESREMOTE_RSYNC}/ \
        ${DESDATA}/ 
"""

#
# not used
#
_QUERY_TEMPLATE="""
select
    fai.path as path,
    fai.filename as filename,
    fai.compression as compression,
    m.band as band,
    m.pfw_attempt_id as pfw_attempt_id

from
    prod.proctag t,
    prod.coadd m,
    prod.file_archive_info fai
where
    t.tag='{campaign}'
    and t.pfw_attempt_id=m.pfw_attempt_id
    and m.tilename='{tilename}'
    and m.filetype='coadd'
    and fai.filename=m.filename
    and fai.archive_name='desar2home' and rownum <= 10\n"""
