#!/usr/bin/env python

# Copyright (C) 2021 Tammo Jan Dijkema
# SPDX-License-Identifier: GPL-3.0-or-later
"""Add FITS metadata and WCS to FF files generated by RMS"""

from glob import glob
import numpy as np

import RMS
from RMS.Formats.Platepar import Platepar
from RMS.Formats.FFfile import getMiddleTimeFF, filenameToDatetime
from RMS.Astrometry.ApplyAstrometry import xyToRaDecPP
import RMS.ConfigReader

from astropy.io import fits
from astropy.io.fits.header import Header
from astropy.time import Time

from fit_wcs import fit_wcs

import os.path
from os.path import join

from argparse import ArgumentParser

import logging

import json

logger = logging.getLogger(__name__)


def add_fffits_metadata(ff_filename, config, platepars_recalibrated,
                      fallback_platepar):
    """
    Add FITS metadata and WCS to FF files generated by RMS

    Args:
        ff_filename (str): full or relative path to FF file
        config (RMS.Config): config instance
        platepars_recalibrated (dict): dictionary with recalibrated platepars
        fallback_platepar (RMS.Platepar): platepar with fitted stars

    Returns:
        None
    """
    ff_basename = os.path.basename(ff_filename)
    platepar_recalibrated = Platepar()
    try:
        platepar_data = platepars_recalibrated[ff_basename]
        with open("platepar_tmp.cal", "w") as f:
            json.dump(platepar_data, f)
        platepar_recalibrated.read("platepar_tmp.cal")
    except (FileNotFoundError, KeyError):
        platepar_recalibrated = fallback_platepar
        logger.warning(f"Using non-recalibrated platepar for {ff_basename}")

    fftime = getMiddleTimeFF(ff_basename, config.fps)

    fit_xy = np.array(fallback_platepar.star_list)[:, 1:3]

    _, fit_ra, fit_dec, _ = xyToRaDecPP([fftime] * len(fit_xy),
                                        fit_xy[:, 0],
                                        fit_xy[:, 1], [1] * len(fit_xy),
                                        platepar_recalibrated,
                                        extinction_correction=False)

    x0 = platepar_recalibrated.X_res / 2
    y0 = platepar_recalibrated.Y_res / 2
    _, ra0, dec0, _ = xyToRaDecPP([fftime], [x0], [y0], [1],
                                  platepar_recalibrated,
                                  extinction_correction=False)
    w = fit_wcs(fit_xy[:, 0],
                fit_xy[:, 1],
                fit_ra,
                fit_dec,
                x0,
                y0,
                ra0[0],
                dec0[0],
                5,
                projection="ZEA")

    hdu_list = fits.open(ff_filename)
    obstime = Time(filenameToDatetime(ff_basename))

    header_meta = {}
    header_meta["OBSERVER"] = config.stationID.strip()
    header_meta["INSTRUME"] = "Global Meteor Network"
    header_meta["MJD-OBS"] = obstime.mjd
    header_meta["DATE-OBS"] = obstime.fits
    header_meta["NFRAMES"] = 256
    header_meta["EXPTIME"] = 256 / config.fps
    header_meta["SITELONG"] = round(config.longitude, 2)
    header_meta["SITELAT"] = round(config.latitude, 2)

    for hdu in hdu_list:
        if hdu.header[
                "NAXIS"] == 0:  # First header is not an image so should not get WCS
            new_header = Header()
        else:
            new_header = w.to_fits(relax=True)[0].header

        for key, value in header_meta.items():
            new_header.append((key, value))

        for key, value in new_header.items():
            if key in hdu.header:
                continue
            hdu.header[key] = value

    hdu_list.writeto(ff_filename, overwrite=True)

def main(dir_path):
    rms_path = os.path.abspath(os.path.dirname(os.path.dirname(RMS.__file__)))

    try:
        config = RMS.ConfigReader.parse(join(dir_path, ".config"))
    except FileNotFoundError:
        logger.warning(f"Could not find .config in {dir_path}, using default")
        config = RMS.ConfigReader.parse(join(rms_path, ".config"))

    try:
        with open(join(dir_path, "platepars_all_recalibrated.json"), "r") as f:
            platepars_recalibrated = json.load(f)
    except FileNotFoundError:
        logger.warning(f"Could not find platepars_recalibrated in {dir_path}")
        platepars_recalibrated = {}

    global_platepar = Platepar()

    if os.path.isfile(join(dir_path, "platepar_cmn2010.cal")):
        global_platepar.read(join(dir_path, "platepar_cmn2010.cal"))
    else:
        logger.warning(
            f"Couldn't find platepar_cmn2010.cal in {dir_path}, using default")
        global_platepar.read(join(rms_path, "platepar_cmn2010.cal"))

    for ff_filename in glob(join(dir_path, "FF*fits")):
        logger.info(f"Updating {ff_filename}")
        add_fffits_metadata(ff_filename, config, platepars_recalibrated,
                            global_platepar)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    parser = ArgumentParser(description="Add metadata to FF fits files")
    parser.add_argument('dir_path',
                        type=str,
                        help="Path to the folder with FF files")

    args = parser.parse_args()

    dir_path = os.path.abspath(args.dir_path)

    main(dir_path)
