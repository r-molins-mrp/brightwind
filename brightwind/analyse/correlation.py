#     brightwind is a library that provides wind analysts with easy to use tools for working with meteorological data.
#     Copyright (C) 2018 Stephen Holleran, Inder Preet
#
#     This program is free software: you can redistribute it and/or modify
#     it under the terms of the GNU Lesser General Public License as published by
#     the Free Software Foundation, either version 3 of the License, or
#     (at your option) any later version.
#
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU Lesser General Public License for more details.
#
#     You should have received a copy of the GNU Lesser General Public License
#     along with this program.  If not, see <https://www.gnu.org/licenses/>.

import numpy as np
import pandas as pd
from typing import List
from brightwind.transform import transform as tf
from brightwind.analyse.plot import _scatter_plot  # WHY NOT HAVE THIS AS A PUBLIC FUNCTION?
from scipy.odr import ODR, RealData, Model
from scipy.linalg import lstsq
from brightwind.analyse.analyse import momm, _binned_direction_series
# from sklearn.svm import SVR as sklearn_SVR
# from sklearn.model_selection import cross_val_score as sklearn_cross_val_score
from brightwind.utils import utils
import pprint
import warnings


__all__ = ['']


class CorrelBase:
    def __init__(self, ref_spd, target_spd, averaging_prd, coverage_threshold=None, ref_dir=None, target_dir=None):
        self.ref_spd = ref_spd
        self.ref_dir = ref_dir
        self.target_spd = target_spd
        self.target_dir = target_dir
        self.averaging_prd = averaging_prd
        self.coverage_threshold = coverage_threshold
        # Get the name of the columns so they can be passed around
        self._ref_spd_col_name = ref_spd.name if ref_spd is not None and isinstance(ref_spd, pd.Series) else None
        self._ref_spd_col_names = ref_spd.columns if ref_spd is not None and isinstance(ref_spd, pd.DataFrame) else None
        self._ref_dir_col_name = ref_dir.name if ref_dir is not None else None
        self._tar_spd_col_name = target_spd.name if target_spd is not None else None
        self._tar_dir_col_name = target_dir.name if target_dir is not None else None
        # Average and merge datasets into one df
        self.data = CorrelBase._averager(self, ref_spd, target_spd, averaging_prd, coverage_threshold,
                                         ref_dir, target_dir)
        self.num_data_pts = len(self.data)
        self.params = {'status': 'not yet run'}

    def _averager(self, ref_spd, target_spd, averaging_prd, coverage_threshold, ref_dir, target_dir):
        # If directions sent, concat speed and direction first
        if ref_dir is not None:
            ref_spd = pd.concat([ref_spd, ref_dir], axis=1)
        if target_dir is not None:
            target_spd = pd.concat([target_spd, target_dir], axis=1)
        data = tf.merge_datasets_by_period(data_1=ref_spd, data_2=target_spd, period=averaging_prd,
                                           coverage_threshold_1=coverage_threshold,
                                           coverage_threshold_2=coverage_threshold,
                                           wdir_column_names_1=self._ref_dir_col_name,
                                           wdir_column_names_2=self._tar_dir_col_name)
        return data

    def show_params(self):
        """Show the dictionary of parameters"""
        pprint.pprint(self.params)

    def plot(self, title=""):
        """For plotting"""
        return _scatter_plot(self.data[self._ref_spd_col_name].values.flatten(),
                             self.data[self._tar_spd_col_name].values.flatten(),
                             self._predict(self.data[self._ref_spd_col_name]).values.flatten(),
                             x_label=self._ref_spd_col_name, y_label=self._tar_spd_col_name)

    def synthesize(self, ext_input=None):
        # This will give erroneous result when the averaging period is not a whole number such that ref and target does
        # bot get aligned - Inder
        if ext_input is None:
            output = self._predict(tf.average_data_by_period(self.ref_spd, self.averaging_prd,
                                                             return_coverage=False))
            output = tf.average_data_by_period(self.target_spd, self.averaging_prd,
                                               return_coverage=False).combine_first(output)
        else:
            output = self._predict(ext_input)
        if isinstance(output, pd.Series):
            return output.to_frame(name=self.target_spd.name + "_Synthesized")
        else:
            output.columns = [self.target_spd.name + "_Synthesized"]
            return output

    def get_r2(self):
        """Returns the r2 score of the model"""
        return 1.0 - (sum((self.data[self._tar_spd_col_name] - self._predict(self.data[self._ref_spd_col_name])) ** 2) /
                      (sum((self.data[self._tar_spd_col_name] - self.data[self._tar_spd_col_name].mean()) ** 2)))

    # def get_error_metrics(self):
    #     raise NotImplementedError


class OrdinaryLeastSquares(CorrelBase):
    """
    Correlate two datasets against each other using the Ordinary Least Squares method. This accepts two wind speed
    Series with timestamps as indexes and an averaging period which merges the datasets by this time period before
    performing the correlation.

    :param ref_spd:            Series containing reference wind speed as a column, timestamp as the index.
    :type ref_spd:             pd.Series
    :param target_spd:         Series containing target wind speed as a column, timestamp as the index.
    :type target_spd:          pd.Series
    :param averaging_prd:      Groups data by the time period specified here. The following formats are supported

            - Set period to '10min' for 10 minute average, '30min' for 30 minute average.
            - Set period to '1H' for hourly average, '3H' for three hourly average and so on for '4H', '6H' etc.
            - Set period to '1D' for a daily average, '3D' for three day average, similarly '5D', '7D', '15D' etc.
            - Set period to '1W' for a weekly average, '3W' for three week average, similarly '2W', '4W' etc.
            - Set period to '1M' for monthly average with the timestamp at the start of the month.
            - Set period to '1A' for annual average with the timestamp at the start of the year.

    :type averaging_prd:       str
    :param coverage_threshold: Minimum coverage to include for correlation
    :type coverage_threshold:  float
    :returns:                  An object representing ordinary least squares fit model

    **Example usage**
    ::
        import brightwind as bw
        data = bw.load_csv(bw.demo_datasets.demo_data)
        m2 = bw.load_csv(bw.demo_datasets.demo_merra2_NE)

        # Correlate on a monthly basis
        ols_cor = bw.Correl.OrdinaryLeastSquares(m2['WS50m_m/s'], data['Spd80mN'], averaging_prd='1M',
                                                 coverage_threshold=0.95)
        ols_cor.run()
        ols_cor.plot()

    """
    def __init__(self, ref_spd, target_spd, averaging_prd, coverage_threshold=0.9):
        CorrelBase.__init__(self, ref_spd, target_spd, averaging_prd, coverage_threshold)

    def __repr__(self):
        return 'Ordinary Least Squares Model ' + str(self.params)

    def run(self, show_params=True):
        p, res = lstsq(np.nan_to_num(self.data[self._ref_spd_col_name].values.flatten()[:, np.newaxis] ** [1, 0]),
                       np.nan_to_num(self.data[self._tar_spd_col_name].values.flatten()))[0:2]

        self.params = dict([('slope', p[0]), ('offset', p[1])])
        self.params['r2'] = self.get_r2()
        self.params['num_data_points'] = self.num_data_pts
        if show_params:
            self.show_params()

    def _predict(self, ref_spd):
        return (ref_spd * self.params['slope']) + self.params['offset']


class OrthogonalLeastSquares(CorrelBase):
    """
    Correlate two datasets against each other using the Orthogonal Least Squares method. This accepts two wind speed
    Series with timestamps as indexes and an averaging period which merges the datasets by this time period before
    performing the correlation.

    :param ref_spd:            Series containing reference wind speed as a column, timestamp as the index.
    :type ref_spd:             pd.Series
    :param target_spd:         Series containing target wind speed as a column, timestamp as the index.
    :type target_spd:          pd.Series
    :param averaging_prd:      Groups data by the time period specified here. The following formats are supported

            - Set period to '10min' for 10 minute average, '30min' for 30 minute average.
            - Set period to '1H' for hourly average, '3H' for three hourly average and so on for '4H', '6H' etc.
            - Set period to '1D' for a daily average, '3D' for three day average, similarly '5D', '7D', '15D' etc.
            - Set period to '1W' for a weekly average, '3W' for three week average, similarly '2W', '4W' etc.
            - Set period to '1M' for monthly average with the timestamp at the start of the month.
            - Set period to '1A' for annual average with the timestamp at the start of the year.

    :type averaging_prd:       str
    :param coverage_threshold: Minimum coverage to include for correlation
    :type coverage_threshold:  float
    :returns:                  An object representing orthogonal least squares fit model

    **Example usage**
    ::
        import brightwind as bw
        data = bw.load_csv(bw.demo_datasets.demo_data)
        m2 = bw.load_csv(bw.demo_datasets.demo_merra2_NE)

        # Correlate on a monthly basis
        orthog_cor = bw.Correl.OrthogonalLeastSquares(m2['WS50m_m/s'], data['Spd80mN'], averaging_prd='1M',
                                                      coverage_threshold=0.95)
        orthog_cor.run()
        orthog_cor.plot()

    """
    @staticmethod
    def linear_func(p, x):
        return p[0] * x + p[1]

    def __init__(self, ref_spd, target_spd, averaging_prd, coverage_threshold=0.9):
        CorrelBase.__init__(self, ref_spd, target_spd, averaging_prd, coverage_threshold)

    def __repr__(self):
        return 'Orthogonal Least Squares Model ' + str(self.params)

    def run(self, show_params=True):
        fit_data = RealData(self.data[self._ref_spd_col_name].values.flatten(), 
                            self.data[self._tar_spd_col_name].values.flatten())
        p, res = lstsq(np.nan_to_num(fit_data.x[:, np.newaxis] ** [1, 0]), 
                       np.nan_to_num(np.asarray(fit_data.y)[:, np.newaxis]))[0:2]
        model = ODR(fit_data, Model(OrthogonalLeastSquares.linear_func), beta0=[p[0][0], p[1][0]])
        output = model.run()
        self.params = dict([('slope', output.beta[0]), ('offset', output.beta[1])])
        self.params['r2'] = self.get_r2()
        self.params['num_data_points'] = self.num_data_pts
        # print("Model output:", output.pprint())
        if show_params:
            self.show_params()

    def _predict(self, ref_spd):
        def linear_func_inverted(x, p):
            return OrthogonalLeastSquares.linear_func(p, x)

        return ref_spd.transform(linear_func_inverted, p=[self.params['slope'], self.params['offset']])


class MultipleLinearRegression(CorrelBase):
    """
    Correlate multiple reference datasets against a target dataset using ordinary least squares. This accepts a
    list of multiple reference wind speeds and a single target wind speed. The wind speed datasets are Pandas
    Series with timestamps as indexes. Also sen is an averaging period which merges the datasets by this time period
    before performing the correlation.

    :param ref_spd:            A list of Series containing reference wind speed as a column, timestamp as the index.
    :type ref_spd:             List(pd.Series)
    :param target_spd:         Series containing target wind speed as a column, timestamp as the index.
    :type target_spd:          pd.Series
    :param averaging_prd:      Groups data by the time period specified here. The following formats are supported

            - Set period to '10min' for 10 minute average, '30min' for 30 minute average.
            - Set period to '1H' for hourly average, '3H' for three hourly average and so on for '4H', '6H' etc.
            - Set period to '1D' for a daily average, '3D' for three day average, similarly '5D', '7D', '15D' etc.
            - Set period to '1W' for a weekly average, '3W' for three week average, similarly '2W', '4W' etc.
            - Set period to '1M' for monthly average with the timestamp at the start of the month.
            - Set period to '1A' for annual average with the timestamp at the start of the year.

    :type averaging_prd:       str
    :param coverage_threshold: Minimum coverage to include for correlation
    :type coverage_threshold:  float
    :returns:                  An object representing Multiple Linear Regression fit model

    **Example usage**
    ::
        import brightwind as bw
        data = bw.load_csv(bw.demo_datasets.demo_data)
        m2_ne = bw.load_csv(bw.demo_datasets.demo_merra2_NE)
        m2_nw = bw.load_csv(bw.demo_datasets.demo_merra2_NW)

        # Correlate on a monthly basis
        mul_cor = bw.Correl.MultipleLinearRegression([m2_ne['WS50m_m/s'], m2_ne['WS50m_m/s']], data['Spd80mN'],
                                                     averaging_prd='1M',
                                                     coverage_threshold=0.95)
        mul_cor.run()

    """
    def __init__(self, ref_spd: List, target_spd, averaging_prd='1H', coverage_threshold=0.9):
        self.ref_spd = self._merge_ref_spds(ref_spd)
        CorrelBase.__init__(self, self.ref_spd, target_spd, averaging_prd, coverage_threshold)

    def __repr__(self):
        return 'Multiple Linear Regression Model ' + str(self.params)

    @staticmethod
    def _merge_ref_spds(ref_spds):
        # ref_spds is a list of pd.Series that may have the same names.
        for idx, ref_spd in enumerate(ref_spds):
            ref_spd.name = ref_spd.name + '_' + str(idx + 1)
        return pd.concat(ref_spds, axis=1, join='inner')

    def run(self, show_params=True):
        p, res = lstsq(np.column_stack((self.data[self._ref_spd_col_names].values, np.ones(len(self.data)))),
                       self.data[self._tar_spd_col_name].values.flatten())[0:2]
        self.params = {'slope': p[:-1], 'offset': p[-1]}
        if show_params:
            self.show_params()

    def show_params(self):
        pprint.pprint(self.params)

    def _predict(self, x):
        def linear_function(x, slope, offset):
            return sum(x * slope) + offset

        return x.apply(linear_function, axis=1, slope=self.params['slope'], offset=self.params['offset'])

    def synthesize(self, ext_input=None):
        # CorrelBase.synthesize(self.data ???????? Why not??????????????????????????????????????
        if ext_input is None:
            return pd.concat([self._predict(tf.average_data_by_period(self.ref_spd.loc[:min(self.data.index)],
                                                                      self.averaging_prd,
                                                                      return_coverage=False)),
                              self.data[self._tar_spd_col_name]], axis=0)
        else:
            return self._predict(ext_input)

    def get_r2(self):
        return 1.0 - (sum((self.data[self._tar_spd_col_name] - 
                           self._predict(self.data[self._ref_spd_col_names])) ** 2) /
                      (sum((self.data[self._tar_spd_col_name] - self.data[self._tar_spd_col_name].mean()) ** 2)))

    def plot(self, title=""):
        raise NotImplementedError


class SimpleSpeedRatio:
    """
    Calculate the simple speed ratio between overlapping datasets and apply to the MOMM of the reference.

    The simple speed ratio is calculated by finding the limits of the overlapping period between the target and
    reference datasets. The ratio of the mean wind speed of these two datasets for the overlapping period is
    calculated i.e. target_overlap_mean / ref_overlap_mean. This ratio is then applied to the Mean of Monthly
    Means (MOMM) of the complete reference dataset resulting in a long term wind speed for the target dataset.

    This is a "back of the envelope" style long term calculation and is intended to be used as a guide and not
    to be used in a robust wind resource assessment.

    A warning message will be raised if the data coverage of either the target or the reference overlapping
    period is poor.

    :param ref_spd:    Series containing reference wind speed as a column, timestamp as the index.
    :type ref_spd:     pd.Series
    :param target_spd: Series containing target wind speed as a column, timestamp as the index.
    :type target_spd:  pd.Series
    :return:           An object representing the simple speed ratio model

    **Example usage**
    ::
        import brightwind as bw
        data = bw.load_csv(bw.demo_datasets.demo_data)
        m2 = bw.load_csv(bw.demo_datasets.demo_merra2_NE)

        # Calculate the simple speed ratio between overlapping datasets
        simple_ratio = bw.Correl.SimpleSpeedRatio(m2['WS50m_m/s'], data['Spd80mN'])
        simple_ratio.run()

    """
    def __init__(self, ref_spd, target_spd):
        self.ref_spd = ref_spd
        self.target_spd = target_spd
        self._start_ts = tf._get_min_overlap_timestamp(ref_spd.dropna().index, target_spd.dropna().index)
        self._end_ts = min(ref_spd.dropna().index.max(), ref_spd.dropna().index.max())
        self.data = ref_spd[self._start_ts:self._end_ts], target_spd[self._start_ts:self._end_ts]
        self.params = {'status': 'not yet run'}

    def __repr__(self):
        return 'Simple Speed Ratio Model ' + str(self.params)

    def run(self, show_params=True):
        self.params = dict()
        simple_speed_ratio = self.data[1].mean() / self.data[0].mean()  # target / ref
        ref_long_term_momm = momm(self.ref_spd)

        # calculate the coverage of the target data to raise warning if poor
        tar_count = self.data[1].dropna().count()
        tar_res = tf._get_data_resolution(self.data[1].index)
        max_pts = (self._end_ts - self._start_ts) / tar_res
        if tar_res == pd.Timedelta(1, unit='M'):  # if is monthly
            # round the result to 0 decimal to make whole months.
            max_pts = np.round(max_pts, 0)
        target_overlap_coverage = tar_count / max_pts

        self.params["simple_speed_ratio"] = simple_speed_ratio
        self.params["ref_long_term_momm"] = ref_long_term_momm
        self.params["target_long_term"] = simple_speed_ratio * ref_long_term_momm
        self.params["target_overlap_coverage"] = target_overlap_coverage
        if show_params:
            self.show_params()

        if target_overlap_coverage < 0.9:
            warnings.warn('\nThe target data overlapping coverage is poor at {}. '
                          'Please use this calculation with caution.'.format(round(target_overlap_coverage, 3)))

    def show_params(self):
        """Show the dictionary of parameters"""
        pprint.pprint(self.params)


class SpeedSort(CorrelBase):
    class SectorSpeedModel:
        def __init__(self, ref_spd, target_spd, cutoff):
            self.sector_ref = ref_spd
            self.sector_target = target_spd
            x_data = sorted([wdspd for wdspd in self.sector_ref.values.flatten()])
            y_data = sorted([wdspd for wdspd in self.sector_target.values.flatten()])
            start_idx = 0
            for idx, wdspd in enumerate(x_data):
                if wdspd >= cutoff:
                    start_idx = idx
                    break
            x_data = x_data[start_idx:]
            y_data = y_data[start_idx:]
            self.target_cutoff = y_data[0]
            self.data_pts = min(len(x_data), len(y_data))
            # Line fit
            mid_pnt = int(len(x_data) / 2)
            xmean1 = np.mean(x_data[:mid_pnt])
            xmean2 = np.mean(x_data[mid_pnt:])
            ymean1 = np.mean(y_data[:mid_pnt])
            ymean2 = np.mean(y_data[mid_pnt:])
            self.params = dict()
            self.params['slope'] = (ymean2 - ymean1) / (xmean2 - xmean1)
            self.params['offset'] = ymean1 - (xmean1 * self.params['slope'])
            # print(self.params)

        def sector_predict(self, x):
            def linear_function(x, slope, offset):
                return x * slope + offset
            return x.transform(linear_function, slope=self.params['slope'], offset=self.params['offset'])

        def plot_model(self, title=None):
            return _scatter_plot(sorted(self.sector_ref.values.flatten()),
                                 sorted(self.sector_target.values.flatten()),
                                 sorted(self.sector_predict(self.sector_ref).values.flatten()))

    def __init__(self, ref_spd, ref_dir, target_spd, target_dir, averaging_prd, coverage_threshold=0.9, sectors=12,
                 direction_bin_array=None, lt_ref_speed=None):
        """
        Correlate two datasets against each other using the SpeedSort method as outlined in 'The SpeedSort, DynaSort
        and Scatter Wind Correlation Methods, Wind Engineering 29(3):217-242, Ciaran King, Brian Hurley, May 2005'.

        This accepts two wind speed and direction Series with timestamps as indexes and an averaging period which
        merges the datasets by this time period before performing the correlation.

        :param ref_spd:             Series containing reference wind speed as a column, timestamp as the index.
        :type ref_spd:              pd.Series
        :param target_spd:          Series containing target wind speed as a column, timestamp as the index.
        :type target_spd:           pd.Series
        :param ref_dir:             Series containing reference wind direction as a column, timestamp as the index.
        :type ref_dir:              pd.Series
        :param target_dir:          Series containing target wind direction as a column, timestamp as the index.
        :type target_dir:           pd.Series
        :param averaging_prd:       Groups data by the time period specified here. The following formats are supported

                - Set period to '10min' for 10 minute average, '30min' for 30 minute average.
                - Set period to '1H' for hourly average, '3H' for three hourly average and so on for '4H', '6H' etc.
                - Set period to '1D' for a daily average, '3D' for three day average, similarly '5D', '7D', '15D' etc.
                - Set period to '1W' for a weekly average, '3W' for three week average, similarly '2W', '4W' etc.
                - Set period to '1M' for monthly average with the timestamp at the start of the month.
                - Set period to '1A' for annual average with the timestamp at the start of the year.

        :type averaging_prd:        str
        :param coverage_threshold:  Minimum coverage to include for correlation
        :type coverage_threshold:   float
        :param sectors:             Number of direction sectors to bin in to. The first sector is centered at 0 by
                                    default. To change that behaviour specify 'direction_bin_array' which overwrites
                                    'sectors'.
        :type sectors:              int
        :param direction_bin_array: An optional parameter where if you want custom direction bins, pass an array
                                    of the bins. To add custom bins for direction sectors, overwrites sectors. For
                                    instance, for direction bins [0,120), [120, 215), [215, 360) the list would
                                    be [0, 120, 215, 360]
        :type direction_bin_array:  List()
        :param lt_ref_speed:        An alternative to the long term wind speed for the reference dataset calculated
                                    using mean of monthly means (MOMM).
        :type lt_ref_speed:         float or int
        :returns:                   An object representing the SpeedSort fit model

        **Example usage**
        ::
            import brightwind as bw
            data = bw.load_csv(bw.demo_datasets.demo_data)
            m2 = bw.load_csv(bw.demo_datasets.demo_merra2_NE)

            # Basic usage on an hourly basis
            ss_cor = bw.Correl.SpeedSort(m2['WS50m_m/s'], m2['WD50m_deg'], data['Spd80mN'], data['Dir78mS'],
                                         averaging_prd='1H')
            ss_cor.run()
            ss_cor.plot_wind_directions()
            ss_cor.get_result_table()
            ss_cor.synthesize()


            # Sending an array of direction sectors
            ss_cor = bw.Correl.SpeedSort(m2['WS50m_m/s'], m2['WD50m_deg'], data['Spd80mN'], data['Dir78mS'],
                                         averaging_prd='1H', direction_bin_array=[0,90,130,200,360])
            ss_cor.run()
        """
        CorrelBase.__init__(self, ref_spd, target_spd, averaging_prd, coverage_threshold, ref_dir=ref_dir,
                            target_dir=target_dir)
        self.sectors = sectors
        self.direction_bin_array = direction_bin_array
        if direction_bin_array is not None:
            self.sectors = len(direction_bin_array) - 1
        if lt_ref_speed is None:
            self.lt_ref_speed = momm(self.data[self._ref_spd_col_name])
        else:
            self.lt_ref_speed = lt_ref_speed
        self.cutoff = min(0.5 * self.lt_ref_speed, 4.0)
        self.ref_veer_cutoff = self._get_veer_cutoff(self.data[self._ref_spd_col_name])
        self.target_veer_cutoff = self._get_veer_cutoff((self.data[self._tar_spd_col_name]))
        self._randomize_calm_periods()
        self._get_overall_veer()
        # for low ref_speed and high target_speed recalculate direction sector
        self._adjust_low_reference_speed_dir()

        self.ref_dir_bins = _binned_direction_series(self.data[self._ref_dir_col_name], sectors,
                                                     direction_bin_array=self.direction_bin_array).rename('ref_dir_bin')
        self.data = pd.concat([self.data, self.ref_dir_bins], axis=1, join='inner')
        self.data = self.data.dropna()
        self.speed_model = dict()

    def __repr__(self):
        return 'SpeedSort Model ' + str(self.params)

    def _randomize_calm_periods(self):
        idxs = self.data[self.data[self._ref_spd_col_name] < 1].index
        self.data.loc[idxs, self._ref_dir_col_name] = 360.0 * np.random.random(size=len(idxs))
        idxs = self.data[self.data[self._tar_spd_col_name] < 1].index
        self.data.loc[idxs, self._tar_dir_col_name] = 360.0 * np.random.random(size=len(idxs))

    def _get_overall_veer(self):
        idxs = self.data[(self.data[self._ref_spd_col_name] >= self.ref_veer_cutoff) &
                         (self.data[self._tar_spd_col_name] >= self.target_veer_cutoff)].index
        self.overall_veer = self._get_veer(self.data.loc[idxs, self._ref_dir_col_name],
                                           self.data.loc[idxs, self._tar_dir_col_name]).mean()

    def _adjust_low_reference_speed_dir(self):
        idxs = self.data[(self.data[self._ref_spd_col_name] < 2) &
                         (self.data[self._tar_spd_col_name] > (self.data[self._ref_spd_col_name] + 4))].index

        self.data.loc[idxs, self._ref_dir_col_name] = (self.data.loc[idxs, self._tar_dir_col_name] -
                                                       self.overall_veer).apply(utils._range_0_to_360)

    @staticmethod
    def _get_veer_cutoff(speed_col):
        return 0.5 * (6.0 + (0.5 * speed_col.mean()))

    @staticmethod
    def _get_veer(ref_d, target_d):
        def change_range(veer):
            if veer > 180:
                return veer - 360.0
            elif veer < -180:
                return veer + 360.0
            else:
                return veer

        v = target_d - ref_d
        return v.apply(change_range)

    def _avg_veer(self, sector_data):
        sector_data = sector_data[(sector_data[self._ref_spd_col_name] >= self.ref_veer_cutoff) &
                                  (sector_data[self._tar_spd_col_name] >= self.target_veer_cutoff)]
        return {'average_veer': self._get_veer(sector_data[self._ref_dir_col_name],
                                               sector_data[self._tar_dir_col_name]).mean(),
                'num_pts_for_veer': len(sector_data[self._ref_dir_col_name])}

    def run(self, show_params=True):
        self.params = dict()
        self.params['Ref_cutoff_for_speed'] = self.cutoff
        self.params['Ref_veer_cutoff'] = self.ref_veer_cutoff
        self.params['Target_veer_cutoff'] = self.target_veer_cutoff
        self.params['Overall_average_veer'] = self.overall_veer
        for sector, group in self.data.groupby(['ref_dir_bin']):
            # print('Processing sector:', sector)
            self.speed_model[sector] = SpeedSort.SectorSpeedModel(ref_spd=group[self._ref_spd_col_name],
                                                                  target_spd=group[self._tar_spd_col_name],
                                                                  cutoff=self.cutoff)
            self.params[sector] = {'slope': self.speed_model[sector].params['slope'],
                                   'offset': self.speed_model[sector].params['offset'],
                                   'target_cutoff': self.speed_model[sector].target_cutoff,
                                   'num_pts_for_speed_fit': self.speed_model[sector].data_pts,
                                   'num_total_pts': min(group.count())}
            self.params[sector].update(self._avg_veer(group))
        if show_params:
            self.show_params()

    def get_result_table(self):
        result = pd.DataFrame()
        for key in self.params:
            if not isinstance(key, str):
                result = pd.concat([pd.DataFrame.from_records(self.params[key], index=[key]), result], axis=0)
        result = result.sort_index()
        return result

    def plot(self):
        for model in self.speed_model:
            self.speed_model[model].plot_model('Sector ' + str(model))
        return self.plot_wind_directions()

    def _predict_dir(self, x_dir):
        sec_veer = []
        for i in range(1, self.sectors+1):
            sec_veer.append(self.params[i]['average_veer'])
        # Add additional entry for first sector
        sec_veer.append(self.params[1]['average_veer'])
        if self.direction_bin_array is None:
            veer_bins = [i*(360/self.sectors) for i in range(0, self.sectors+1)]
        else:
            veer_bins = [self.direction_bin_array[i]+self.direction_bin_array[i+1]/2.0
                         for i in range(0, len(self.direction_bin_array)-1)]
        x = pd.concat([x_dir.dropna().rename('dir'), _binned_direction_series(x_dir.dropna(), self.sectors,
                       direction_bin_array=veer_bins).rename('veer_bin')], axis=1, join='inner')
        x['sec_mid_pt'] = [veer_bins[i-1] for i in x['veer_bin']]
        x['ratio'] = (x['dir'] - x['sec_mid_pt'])/(360.0/self.sectors)
        x['sec_veer'] = [sec_veer[i - 1] for i in x['veer_bin']]
        x['multiply_factor'] = [sec_veer[i]-sec_veer[i-1] for i in x['veer_bin']]
        x['adjustment'] = x['sec_veer'] + (x['ratio']*x['multiply_factor'])
        return (x['dir'] + x['adjustment']).sort_index().apply(utils._range_0_to_360)

    def _predict(self, x_spd, x_dir):
        x = pd.concat([x_spd.dropna().rename('spd'),
                       _binned_direction_series(x_dir.dropna(), self.sectors,
                                                direction_bin_array=self.direction_bin_array).rename('ref_dir_bin')],
                      axis=1, join='inner')
        prediction = pd.DataFrame()
        first = True
        for sector, data in x.groupby(['ref_dir_bin']):
            if first is True:
                first = False
                prediction = self.speed_model[sector].sector_predict(data['spd'])
            else:
                prediction = pd.concat([prediction, self.speed_model[sector].sector_predict(data['spd'])], axis=0)

        return prediction.sort_index()

    def synthesize(self, input_spd=None, input_dir=None):
        # This will give erroneous result when the averaging period is not a whole number such that ref and target does
        # bot get aligned -Inder
        if input_spd is None and input_dir is None:
            output = self._predict(tf.average_data_by_period(self.ref_spd, self.averaging_prd,
                                                             return_coverage=False),
                                   tf.average_data_by_period(self.ref_dir, self.averaging_prd,
                                                             return_coverage=False))
            output = tf.average_data_by_period(self.target_spd, self.averaging_prd,
                                               return_coverage=False).combine_first(output)
            dir_output = self._predict_dir(tf.average_data_by_period(self.ref_dir, self.averaging_prd,
                                                                     return_coverage=False))

        else:
            output = self._predict(input_spd, input_dir)
            dir_output = self._predict_dir(input_dir)
        output[output < 0] = 0
        return pd.concat([output.rename(self._tar_spd_col_name + "_Synthesized"),
                          dir_output.rename(self._tar_dir_col_name + "_Synthesized")], axis=1, join='inner')

    def plot_wind_directions(self):
        """
        Plots reference and target directions in a scatter plot
        """
        return _scatter_plot(
            self.data[self._ref_dir_col_name][(self.data[self._ref_spd_col_name] > self.cutoff) &
                                              (self.data[self._tar_spd_col_name] > self.cutoff)],
            self.data[self._tar_dir_col_name][(self.data[self._ref_spd_col_name] > self.cutoff) &
                                              (self.data[self._tar_spd_col_name] > self.cutoff)],
            x_label=self._ref_dir_col_name, y_label=self._tar_dir_col_name)


class SVR:
    def __init__(self, ref_spd, target_spd, averaging_prd, coverage_threshold, bw_model=0, **sklearn_args):
        raise NotImplementedError
    #     CorrelBase.__init__(self, ref_spd, target_spd, averaging_prd, coverage_threshold)
    #     bw_models = [{'kernel': 'rbf', 'C': 30, 'gamma': 0.01}, {'kernel': 'linear', 'C': 10}]
    #     self.model = sklearn_SVR(**{**bw_models[bw_model], **sklearn_args})
    #
    # def __repr__(self):
    #     return 'Support Vector Regression Model ' + str(self.params)
    #
    # def run(self, show_params=True):
    #     if len(self.data[self._ref_spd_col_name].values.shape) == 1:
    #         x = self.data[self._ref_spd_col_name].values.reshape(-1, 1)
    #     else:
    #         x = self.data[self._ref_spd_col_name].values
    #     self.model.fit(x, self.data[self._tar_spd_col_name].values.flatten())
    #     self.params = dict()
    #     self.params['RMSE'] = -1 * sklearn_cross_val_score(self.model, x,
    #                                                        self.data[self._tar_spd_col_name].values.flatten(),
    #                                                        scoring='neg_mean_squared_error', cv=3)
    #     self.params['MAE'] = -1 * sklearn_cross_val_score(self.model, x,
    #                                                       self.data[self._tar_spd_col_name].values.flatten(),
    #                                                       scoring='neg_mean_absolute_error', cv=3)
    #     self.params['Explained Variance'] = -1 * sklearn_cross_val_score(self.model, x,
    #                                                                      self.data[self._tar_spd_col_name].values.flatten(),
    #                                                                      scoring='explained_variance', cv=3)
    #     if show_params:
    #         self.show_params()
    #
    # def _predict(self, x):
    #     if isinstance(x, pd.Series):
    #         X = x.values.reshape(-1, 1)
    #         return pd.DataFrame(data=self.model.predict(X), index=x.index)
    #     elif isinstance(x, pd.DataFrame):
    #         X = x.values
    #         return pd.DataFrame(data=self.model.predict(X), index=x.index)
    #     else:
    #         if not len(x.shape) == 2:
    #             raise ValueError("Expected shape of input data (num of data points, number of reference datasets), "
    #                              "but found ", x.shape)
    #         else:
    #             return self.model.predict(x)
    #
    # def plot(self, title=""):
    #     """For plotting"""
    #     _scatter_plot(self.data[self._ref_spd_col_name].values.flatten(),
    #                   self.data[self._tar_spd_col_name].values.flatten(),
    #                   self._predict(self.data[self._ref_spd_col_name]).values.flatten(), prediction_marker='.',
    #                   x_label=self._ref_spd_col_name, y_label=self._tar_spd_col_name)
