from __future__ import division
import numpy as np
import pandas as pd
import scipy
import sys
import os
import string
import shutil
import datetime

path_data_df = pd.read_csv(filepath_or_buffer='path_data.csv', delimiter=',', comment='#', header=[0], skip_blank_lines=True, index_col=[0])

code_folder_path = path_data_df.loc['Code Folder'].values[0].replace('\\', '/')
fosof_analyzed_data_folder_path = path_data_df.loc['FOSOF Analyzed Data Folder'].values[0].replace('\\', '/')
wvg_calib_data_folder_path = path_data_df.loc['Waveguide Calibration Folder'].values[0].replace('\\', '/')
krytar109B_pwr_det_calib_folder_path = path_data_df.loc['KRYTAR 109 B Power Detector Calibration Data Folder'].values[0].replace('\\', '/')
sim_data_folder_path = path_data_df.loc['Simulation Data Folder'].values[0].replace('\\', '/')

sys.path.insert(0, code_folder_path)

from exp_data_analysis import *
from fosof_data_set_analysis import *
from ZX47_Calibration_analysis import *
from KRYTAR_109_B_Calib_analysis import *

from hydrogen_sim_data import *

os.chdir(code_folder_path)
from wvg_power_calib_raw_data_analysis_Old import *
os.chdir(code_folder_path)
from wvg_power_calib_analysis import *

import re
import time
import math
import copy
import pickle

import numpy.fft
import scipy.fftpack
import scipy.interpolate

import matplotlib.pyplot as plt

# Package for wrapping long string to a paragraph
import textwrap

#%%
''' Calibration data at 4 cm for different accelerating voltage of 22.17 kV vs 49.86 kV.

Only single calibration data set was acquired. The purpose is to compare the calibrations obtained for the same waveguide separation but different accelerating voltages. We expect, if the analysis is correct, to get the same calibration curve.

Data set: 180522-195929 - Waveguide Calibration - 0 config, PD ON 82.5 V, 22.17 kV, 908-912 MHz

'''

# Separation: 4 cm
# Starting data set:
# 2018-05-14 15:06:58
# Final data set:
# 2018-06-15 16:40:59

exp_folder_name_list = [
    '180522-195929 - Waveguide Calibration - 0 config, PD ON 82.5 V, 22.17 kV, 908-912 MHz'
]

data_set_df = None
for exp_folder_name in exp_folder_name_list:

    data_set = DataSetQuenchCurveWaveguide(exp_folder_name, load_Q=True)
    data_set.average_surv_frac_data()
    if data_set.loaded_Q == False:
        data_set.save_instance()

    df = pd.DataFrame(pd.Series({exp_folder_name: data_set}, name='Data Set'))

    if data_set_df is None:
        data_set_df = df
    else:
        data_set_df = data_set_df.append(df)

data_set_df.index.names = ['Experiment Folder Name']
#%%
# Take a look at the DC value over time for one of the particular data sets. This is basically to show that one cannot assume that the standard deviation in the mean of the digitizer trace is a good indicator in the stability of DC over the course of power scan for a given frequency.
data_set = data_set_df.iloc[0]['Data Set']

fig, ax = plt.subplots()
fig.set_size_inches(15, 10)

ax = data_set.get_beam_dc_rf_off().reset_index().plot(kind='scatter', x='Elapsed Time [s]', y='DC [V]', yerr = 'DC STDOM [V]', ax=ax, color='black')

x_arr, y_arr = data_set.get_beam_dc_rf_off_plotting_data(ax)

ax.plot(x_arr, y_arr, color='blue')

plt.show()
#%%
# Combine the averaged surviving fractions from all of the data sets together.
data_set_grouped_df = data_set_df.groupby('Experiment Folder Name')

surv_frac_av_df = data_set_grouped_df.apply(lambda df: df['Data Set'].iloc[0].average_surv_frac_data()).reset_index(level='Experiment Folder Name', drop=True).sort_index()
#%%
# Beam speed to use for the simulation [cm/ns]. Accelerating voltage is 22.17 kV. This was later measured to correspond to 0.2254 cm/ns.
v_speed = 0.2254
#%%
# Load power scan simulation data that corresponds to the particular beam speed.
old_sim_info_df = OldSimInfo().get_info()

old_quench_sim_info_df = old_sim_info_df[old_sim_info_df['Waveguide Electric Field [V/cm]'] == 'Power Scan']

old_quench_sim_info_df = old_quench_sim_info_df[old_quench_sim_info_df['Speed [cm/ns]'] == v_speed]
#%%
# In general there are several available simulations. Pick one of them.
# Waveguide Quenching simulation to use
old_quench_sim_info_s = old_quench_sim_info_df.iloc[0]
#%%
# Use the simulation file to obtain the analyzed simulation class instance.
old_quench_sim_set = WaveguideOldQuenchCurveSimulationSet(old_quench_sim_info_s)
sim_name_list = old_quench_sim_set.get_list_of_simulations()
sim_name_list
#%%
sim_name_list[2]
#%%
# We use 1.8 mm off-axis simulation, because this is the RMS beam radius that was determined by using Monte Carlo simulation using distances between and diameters of apertures.
quench_sim_vs_freq_df = old_quench_sim_set.get_simulation_data(sim_name_list[2])
#%%
#%%
# Fractional DC offset for the data sets. This is the fractional offset that is determined by having 1088 and 1147 quench cavities set to pi-pulse and find the ratio of the Detector signal with one of the waveguides set to pi-pulse to the Detetor signal when both of the waveguides have no RF power going into them.

# This is the maximum allowed fractional DC offset that will not result in negative DC On/Off ratios
max_fract_DC_offset_allowed = np.min(surv_frac_av_df['DC On/Off Ratio'].values)
#%%
max_fract_DC_offset_allowed
#%%
def check_fract_offset(fract_DC_offset):
    if fract_DC_offset > max_fract_DC_offset_allowed:
        print('Fractional offset is larger than the maximum allowed fractional DC offset! Returning the maximum allowed offset.')
        return max_fract_DC_offset_allowed
    else:
        return fract_DC_offset

# Fractional offset to use. Here I am using 0.02 instead of 0.03. The logic behind this is the following. By looking at the quench cavities quench curves I remember seeing that the quench offset was decreasing roughly linearly with power. I do not remember the slope, however. What I see is that the maximum allowed fractional DC offset is about 0.027 vs about 0.4, which is about 1.5 times smaller, which is the same as fraction by which the atoms spend more time inside the quench cavities when at 22.17 kV vs 49.86 kV. That is why I reduce the fractional offset by a factor of 1.5, which results in 0.02.
fract_DC_offset = 0.02


fract_DC_offset = check_fract_offset(fract_DC_offset)

# Off axis distance of the atoms in the simulation.
off_axis_dist = 1.8

# Settings for the Waveguides power calibration.
wvg_calib_param_dict =    {
            'Date [date object]': datetime.date(year=2018, month=5, day=22),
            'Waveguide Separation [cm]': 4,
            'Accelerating Voltage [kV]': 22.17,
            'RF Frequency Scan Range [MHz]': '894-926',
            'Atom Off-Axis Distance (Simulation) [mm]': 1.8,
            'Fractional DC Offset': fract_DC_offset,
            'Minimum RF E Field Amplitude [V/cm]': 5,
            'Maximum RF E Field Amplitude [V/cm]': 27,
            'Use Boundary Conditions': False,
            'Polynomial Fit Order': 4
                    }
#%%
wvg_calib_analysis = WaveguideCalibrationAnalysis(load_Q=False, quench_sim_vs_freq_df=quench_sim_vs_freq_df, surv_frac_av_df=surv_frac_av_df, wvg_calib_param_dict=wvg_calib_param_dict)

quench_sim_data_sets_df = wvg_calib_analysis.analyze_simulation_quench_curves()
surv_frac_converted_df = wvg_calib_analysis.extract_E_fields()

# RF E Field amplitude vs RF power parameters fit curves.
extracted_E_field_vs_RF_power_fits_set_df = wvg_calib_analysis.get_converted_E_field_curve_fits()
# DC On/Off Ratio vs RF power parameters fit curves
surv_frac_vs_RF_power_fits_set_df = wvg_calib_analysis.get_quench_curve_fits()
#%%
# Plotting the extracted fit curves
rf_freq = 910.1
rf_channel = 'A'
#%%
fig, axes = plt.subplots(nrows=3, ncols=3)
fig.set_size_inches(22,20)
axes = wvg_calib_analysis.plot_extracted_E_field_curves(rf_channel, rf_freq, axes)

plt.show()
extracted_E_field_vs_RF_power_fits_set_df.loc[rf_channel, rf_freq]
#%%
fig, axes = plt.subplots(nrows=3, ncols=3)
fig.set_size_inches(22,20)
axes = wvg_calib_analysis.plot_quench_curve(rf_channel, rf_freq, axes)

plt.show()
surv_frac_vs_RF_power_fits_set_df.loc[rf_channel, rf_freq]

#%%
# Perform RF power parameters' calibration for each RF E field requested.
rf_e_field_calib_df = wvg_calib_analysis.perform_power_calib()
calib_av_df = wvg_calib_analysis.get_av_calib_data()
#%%
rf_e_field_ampl = 5.0
rf_channel = 'A'

fig, axes = plt.subplots(nrows=1, ncols=4)

fig.set_size_inches(24, 8)

axes = wvg_calib_analysis.get_calibration_plot(rf_channel, rf_e_field_ampl, axes)

plt.show()
#%%
wvg_calib_analysis.save_instance()
#%%
fract_DC_offset_half = fract_DC_offset * 0.5


fract_DC_offset_half = check_fract_offset(fract_DC_offset_half)

# Settings for the Waveguides power calibration.
wvg_calib_param_dict =    {
            'Date [date object]': datetime.date(year=2018, month=5, day=22),
            'Waveguide Separation [cm]': 4,
            'Accelerating Voltage [kV]': 22.17,
            'RF Frequency Scan Range [MHz]': '894-926',
            'Atom Off-Axis Distance (Simulation) [mm]': 1.8,
            'Fractional DC Offset': fract_DC_offset_half,
            'Minimum RF E Field Amplitude [V/cm]': 5,
            'Maximum RF E Field Amplitude [V/cm]': 27,
            'Use Boundary Conditions': False,
            'Polynomial Fit Order': 4
                        }
# We now calculate the calibration for the case when the fractional offset is 50% smaller.
wvg_calib_analysis_half = WaveguideCalibrationAnalysis(load_Q=False, quench_sim_vs_freq_df=quench_sim_vs_freq_df, surv_frac_av_df=surv_frac_av_df, wvg_calib_param_dict=wvg_calib_param_dict)

quench_sim_data_sets_df = wvg_calib_analysis_half.analyze_simulation_quench_curves()
surv_frac_converted_df = wvg_calib_analysis_half.extract_E_fields()

# RF E Field amplitude vs RF power parameters fit curves.
extracted_E_field_vs_RF_power_fits_set_df = wvg_calib_analysis_half.get_converted_E_field_curve_fits()
# DC On/Off Ratio vs RF power parameters fit curves
surv_frac_vs_RF_power_fits_set_df = wvg_calib_analysis_half.get_quench_curve_fits()
#%%
# Plotting the extracted fit curves
rf_freq = 910.0
rf_channel = 'A'
#%%
fig, axes = plt.subplots(nrows=3, ncols=3)
fig.set_size_inches(22,20)
axes = wvg_calib_analysis_half.plot_extracted_E_field_curves(rf_channel, rf_freq, axes)

plt.show()
extracted_E_field_vs_RF_power_fits_set_df.loc[rf_channel, rf_freq]
#%%
fig, axes = plt.subplots(nrows=3, ncols=3)
fig.set_size_inches(22,20)
axes = wvg_calib_analysis_half.plot_quench_curve(rf_channel, rf_freq, axes)

plt.show()
surv_frac_vs_RF_power_fits_set_df.loc[rf_channel, rf_freq]
#%%
# Perform RF power parameters' calibration for each RF E field requested.
rf_e_field_calib_df = wvg_calib_analysis_half.perform_power_calib()
calib_av_df = wvg_calib_analysis_half.get_av_calib_data()
#%%
rf_e_field_ampl = 5.0
rf_channel = 'A'

fig, axes = plt.subplots(nrows=1, ncols=4)

fig.set_size_inches(24, 8)

axes = wvg_calib_analysis_half.get_calibration_plot(rf_channel, rf_e_field_ampl, axes)
plt.show()
#%%
wvg_calib_analysis_half.save_instance()
#%%
# We now calculate the calibration for the case when the fractional offset is 50% larger.

fract_DC_offset_plus_half = fract_DC_offset * 1.5
fract_DC_offset_plus_half = check_fract_offset(fract_DC_offset_plus_half)

# Settings for the Waveguides power calibration.
wvg_calib_param_dict =    {
            'Date [date object]': datetime.date(year=2018, month=5, day=22),
            'Waveguide Separation [cm]': 4,
            'Accelerating Voltage [kV]': 22.17,
            'RF Frequency Scan Range [MHz]': '894-926',
            'Atom Off-Axis Distance (Simulation) [mm]': 1.8,
            'Fractional DC Offset': fract_DC_offset_plus_half,
            'Minimum RF E Field Amplitude [V/cm]': 5,
            'Maximum RF E Field Amplitude [V/cm]': 27,
            'Use Boundary Conditions': False,
            'Polynomial Fit Order': 4
                        }

wvg_calib_analysis_plus_half = WaveguideCalibrationAnalysis(load_Q=False, quench_sim_vs_freq_df=quench_sim_vs_freq_df, surv_frac_av_df=surv_frac_av_df, wvg_calib_param_dict=wvg_calib_param_dict)

quench_sim_data_sets_df = wvg_calib_analysis_plus_half.analyze_simulation_quench_curves()
surv_frac_converted_df = wvg_calib_analysis_plus_half.extract_E_fields()

# RF E Field amplitude vs RF power parameters fit curves.
extracted_E_field_vs_RF_power_fits_set_df = wvg_calib_analysis_plus_half.get_converted_E_field_curve_fits()
# DC On/Off Ratio vs RF power parameters fit curves
surv_frac_vs_RF_power_fits_set_df = wvg_calib_analysis_plus_half.get_quench_curve_fits()
#%%
# Plotting the extracted fit curves
rf_freq = 910.0
rf_channel = 'A'
#%%
fig, axes = plt.subplots(nrows=3, ncols=3)
fig.set_size_inches(22,20)
axes = wvg_calib_analysis_plus_half.plot_extracted_E_field_curves(rf_channel, rf_freq, axes)

plt.show()
extracted_E_field_vs_RF_power_fits_set_df.loc[rf_channel, rf_freq]
#%%
fig, axes = plt.subplots(nrows=3, ncols=3)
fig.set_size_inches(22,20)
axes = wvg_calib_analysis_plus_half.plot_quench_curve(rf_channel, rf_freq, axes)

plt.show()
surv_frac_vs_RF_power_fits_set_df.loc[rf_channel, rf_freq]
#%%
# Perform RF power parameters' calibration for each RF E field requested.
rf_e_field_calib_df = wvg_calib_analysis_plus_half.perform_power_calib()
calib_av_df = wvg_calib_analysis_plus_half.get_av_calib_data()
#%%
rf_e_field_ampl = 18.0
rf_channel = 'A'

fig, axes = plt.subplots(nrows=1, ncols=4)

fig.set_size_inches(24, 8)

axes = wvg_calib_analysis_plus_half.get_calibration_plot(rf_channel, rf_e_field_ampl, axes)

plt.show()
#%%
wvg_calib_analysis_plus_half.save_instance()
#%%
rf_e_field_ampl = 8.0
rf_channel = 'A'

# Comparison between the calibration curves obtained for various fractional DC offsets. The fractional deviations tells us the range of different powers that we can set for the RF waveguides. This at the same time gives us the idea of the uncertainty in the RF power in the waveguides, because if at larger fractional DC offset we need to put roughly 10% more power into the RF system, it means that the RF power inside the waveguides is 10% larger for the larger fractional DC offset.

figure, axes = plt.subplots(nrows=1, ncols=3)

figure.set_size_inches(16, 12)

wvg_calib_analysis.calib_av_df.loc[rf_channel, rf_e_field_ampl]['RF System Power Sensor Detected Power [mW]'].reset_index().plot(kind='scatter', x=freq_column_name, y='Mean Value', ax=axes[0], color='black', label=str(fract_DC_offset))

wvg_calib_analysis_half.calib_av_df.loc[rf_channel, rf_e_field_ampl]['RF System Power Sensor Detected Power [mW]'].reset_index().plot(kind='scatter', x=freq_column_name, y='Mean Value', ax=axes[0], color='blue', label=str(round(fract_DC_offset_half, 3)))

wvg_calib_analysis_plus_half.calib_av_df.loc[rf_channel, rf_e_field_ampl]['RF System Power Sensor Detected Power [mW]'].reset_index().plot(kind='scatter', x=freq_column_name, y='Mean Value', ax=axes[0], color='red', label=str(round(fract_DC_offset_plus_half, 3)))

axes[0].set_ylabel('RF System Power Sensor Detected Power [mW]')

(wvg_calib_analysis_half.calib_av_df.loc[rf_channel, rf_e_field_ampl]['RF System Power Sensor Detected Power [mW]']/wvg_calib_analysis.calib_av_df.loc[rf_channel, rf_e_field_ampl]['RF System Power Sensor Detected Power [mW]'] - 1).reset_index().plot(kind='scatter', x=freq_column_name, y='Mean Value', ax=axes[1], color='blue', label=str(round(fract_DC_offset_half, 3)))

(wvg_calib_analysis_plus_half.calib_av_df.loc[rf_channel, rf_e_field_ampl]['RF System Power Sensor Detected Power [mW]']/wvg_calib_analysis.calib_av_df.loc[rf_channel, rf_e_field_ampl]['RF System Power Sensor Detected Power [mW]'] - 1).reset_index().plot(kind='scatter', x=freq_column_name, y='Mean Value', ax=axes[1], color='red', label=str(round(fract_DC_offset_plus_half, 3)))

axes[1].set_ylabel('Fractional deviation')

(wvg_calib_analysis_half.calib_av_df.loc[rf_channel, rf_e_field_ampl]['RF System Power Sensor Detected Power [mW]'] - wvg_calib_analysis.calib_av_df.loc[rf_channel, rf_e_field_ampl]['RF System Power Sensor Detected Power [mW]']).reset_index().plot(kind='scatter', x=freq_column_name, y='Mean Value', ax=axes[2], color='blue', label=str(round(fract_DC_offset_half, 3)))

(wvg_calib_analysis_plus_half.calib_av_df.loc[rf_channel, rf_e_field_ampl]['RF System Power Sensor Detected Power [mW]'] - wvg_calib_analysis.calib_av_df.loc[rf_channel, rf_e_field_ampl]['RF System Power Sensor Detected Power [mW]']).reset_index().plot(kind='scatter', x=freq_column_name, y='Mean Value', ax=axes[2], color='red', label=str(round(fract_DC_offset_plus_half, 3)))

axes[2].set_ylabel('Deviation [mW]')

plt.show()
#%%
# Here I calculate the average error in the RF power in the waveguides. The assumption here is that the effect due to the fractional DC offset at all of the RF resonant frequencies in the scan range is similar. This can be easily checked by simply calculating the STD of the fractional deviations.
# Now, most likely the 50% larger fractional DC offset will not be able to get applied to the data, because DC On/Off fractions become negative. However, it does not mean, actually, that the fractional DC offset cannot be 50% larger for those cases, because it is quite possible that we are also quenching the offset with the waveguides, so that at the pi-pulse we actually observed smaller offset, than it actually is. I guess the question is, can the quenching offset then be smaller than the one we determine at pi-pulse? I actually do not know the mechanism for this. But we can only calculate the average error deviation for the case when the fractional DC offset is 50% smaller, which does not seem to be possible on physical grounds. Thus the obvious assumption to make is that We are forced to assume, however, that the average power error is the same (but oppositve in sign) for the case when the fractional DC offset is 50% larger.
# It is also true that the uncertainty for the case when the offset is 50% smaller, the fractional error is larger than the case when the offset is 50% larger, which is good for us - we are not underestimating the systematic uncertainty this way.
#
av_RF_power_calib_error_df = (wvg_calib_analysis_half.calib_av_df['RF System Power Sensor Detected Power [mW]']['Mean Value']/wvg_calib_analysis.calib_av_df['RF System Power Sensor Detected Power [mW]']['Mean Value']-1).groupby(['E Field [V/cm]']).aggregate(['mean', lambda x: np.std(x, ddof=1)/np.sqrt(x.shape[0])]).rename(columns={'mean': 'Mean Fractional Error [%]', '<lambda>': 'Fractional Error STDOM [%]'})

av_RF_power_calib_error_df = av_RF_power_calib_error_df * 100

av_RF_power_calib_error_df = av_RF_power_calib_error_df.reset_index()
av_RF_power_calib_error_df['E Field [V/cm]'] = av_RF_power_calib_error_df['E Field [V/cm]']**2
av_RF_power_calib_error_df.rename(columns={'E Field [V/cm]':'Proportional To RF Power [V^2/cm^2]'}, inplace=True)
av_RF_power_calib_error_df = av_RF_power_calib_error_df.set_index('Proportional To RF Power [V^2/cm^2]')
av_RF_power_calib_error_df
#%%
# Save the average RF power calibration error in the power calibration with the initial fractional DC offset.
wvg_calib_analysis.set_av_rf_power_calib_error(av_RF_power_calib_error_df)
wvg_calib_analysis.save_instance()
#%%
