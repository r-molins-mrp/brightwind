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

import os
import pandas as pd

__all__ = ['export_tab_file','export_to_csv']



def export_tab_file(freq_tab, name, lat, long, height=0.0, dir_offset=0.0):
    """
    Export a WaSP tab file from freq_table() function

    :param freq_tab: Tab file
    :param name: Name of the file or location
    :param lat: Latitude of the site location
    :type lat: float
    :param long: Longitude of the site location
    :type long: float
    :param height: Height of the device, default is 0.0
    :type height: float
    :param dir_offset: Direction offset, default 0.0
    :type dir_offset: float
    :return: Creates a windographer file with the name specified by name

    **Exampe Usage**
    ::
        import brightwind as bw
        df = bw.load_campbell_scientific(bw.datasets.demo_campbell_scientific_site_data)
        graph, tab = bw.freq_table(df.Spd40mN, df.Dir38mS, return_data=True)
        bw.export_tab_file(tab, name='campbell_tab_file', lat=10, long=10)

    """
    local_freq_tab = freq_tab.copy()
    lat = float(lat)
    long = float(long)
    speed_interval = {interval.right - interval.left for interval in local_freq_tab.index}
    if len(speed_interval)is not 1:
        import warnings
        warnings.warn("All speed bins not of equal lengths")
    speed_interval = speed_interval.pop()
    sectors = len(local_freq_tab.columns)
    freq_sum = local_freq_tab.sum(axis=0)
    local_freq_tab.index = [interval.right for interval in local_freq_tab.index]

    tab_string = str(name)+"\n "+"{:.2f}".format(lat)+" "+"{:.2f}".format(long)+" "+"{:.2f}".format(height)+"\n " + \
                 "{:.2f}".format(sectors)+" "+"{:.2f}".format(speed_interval)+" "+"{:.2f}".format(dir_offset)+"\n "
    tab_string += " ".join("{:.2f}".format(percent) for percent in freq_sum.values)+"\n"
    for column in local_freq_tab.columns:
        local_freq_tab[column] = (local_freq_tab[column] / sum(local_freq_tab[column])) * 1000.0
    tab_string += local_freq_tab.to_string(header=False, float_format='%.2f', na_rep=0.00)
    with open(str(name)+".tab", "w") as file:
        file.write(tab_string)


def export_to_csv(data, file_path, file_name ='brightwindexport',**kwargs):
    """
    Export a DataFrame, Series or Array to a .CSV file. The pandas.to_csv documentation can be found at
    https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.DataFrame.to_csv.html

    :param data: Dataframe or Series
    :type data: panda.Dataframe or pandas.Series
    :param file_name: The file name under which the CSV will be saved, or use the default 'brightwindexport'
    :type file_name: str
    :param file_path: the directory where the CSV will be saved
    :type file_path: str
    :return exports a CSV file to a location of the user's choosing
    **Example usage**
        ::
        import brightwind as bw
        df = bw.load_csv(r'C:\\some\\folder\\some_CR1000_data.csv')
        file_path = r'C:\\some\\folder\\'
        bw.export_to_csv(df,file_path, file_name = 'BrightwindCalculations' )

    """
    # Check if the proposed destination folder exists
    folder_present = os.path.isdir(file_path, **kwargs)

    if folder_present:
        file_name = file_name + ".csv"
        pathfile = os.path.normpath(os.path.join(file_path, file_name))
        files_present = os.path.isfile(pathfile, **kwargs)
        # if no files by the name are present, export to CSV
        if not files_present:
            if isinstance(data, (pd.DataFrame,pd.Series)):
                data.to_csv(pathfile,**kwargs)
            else:
                pd.DataFrame(data).to_csv(pathfile, **kwargs)

        # if a file by the chosen name is present, confirm overwrite or specify a new name
        else:
            overwrite = input("WARNING: " + pathfile + " already exists! Do you want to overwrite <y/n>? \n ")
            if overwrite == 'y':
                if isinstance(data, (pd.DataFrame, pd.Series)):
                    data.to_csv(pathfile, **kwargs)
                else:
                    pd.DataFrame(data).to_csv(pathfile,**kwargs)
            elif overwrite == 'n':
                new_filename = input("Type new filename: \n ") + ".csv"
                pathfile = os.path.normpath(os.path.join(file_path, new_filename))
                if isinstance(data, (pd.DataFrame, pd.Series)):
                    data.to_csv(pathfile, **kwargs)
                else:
                    pd.DataFrame(data).to_csv(pathfile, **kwargs)
            else:
                print( "Not a valid input. Data is NOT saved!\n")

    else:
        # If the proposed folder is not present return an error
        raise FileNotFoundError("The destination folder doesn't seem to exist.")





