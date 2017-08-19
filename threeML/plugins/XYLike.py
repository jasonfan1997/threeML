from threeML.plugin_prototype import PluginPrototype
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import copy

from threeML.plugin_prototype import PluginPrototype

from astromodels import Model, PointSource

from threeML.plugins.OGIP.likelihood_functions import poisson_log_likelihood_ideal_bkg
from threeML.plugins.OGIP.likelihood_functions import half_chi2
from threeML.classicMLE.joint_likelihood import JointLikelihood
from threeML.data_list import DataList
from threeML.classicMLE.goodness_of_fit import GoodnessOfFit

__instrument_name = "n.a."


class XYLike(PluginPrototype):

    def __init__(self, name, x, y, yerr=None, poisson_data=False, quiet=False, source_name=None):

        nuisance_parameters = {}

        super(XYLike, self).__init__(name, nuisance_parameters)

        # Make x and y always arrays so we can handle them always in the same way
        # even if they have only one element

        self._x = np.array(x, ndmin=1)
        self._y = np.array(y, ndmin=1)

        # If there are specified errors, use those (assume Gaussian statistic)
        # otherwise make sure that the user specified poisson_error = True and use
        # Poisson statistic

        if yerr is not None:

            self._yerr = np.array(yerr, ndmin=1)

            assert np.all(self._yerr > 0), "Errors cannot be negative or zero."

            if not quiet:

                print("Using Gaussian statistic (equivalent to chi^2) with the provided errors.")

            self._is_poisson = False

            self._has_errors = True

        elif not poisson_data:

            self._yerr = np.ones_like(self._y)

            self._is_poisson = False

            self._has_errors = False

            if not quiet:

                print("Using unweighted Gaussian (equivalent to chi^2) statistic.")

        else:

            if not quiet:

                print("Using Poisson log-likelihood")

            self._is_poisson = True
            self._yerr = None
            self._has_errors = True

        # This will keep track of the simulated datasets we generate
        self._n_simulated_datasets = 0

        # This will contain the JointLikelihood object after a call to .fit()
        self._joint_like_obj = None

        self._likelihood_model = None
        # currently not used by XYLike, but needed for subclasses

        self._mask = np.ones(self._x.shape, dtype=bool)

        # This is the name of the source this SED refers to (if it is a SED)
        self._source_name = source_name

    @classmethod
    def from_function(cls, name, function, x, yerr):

        y = function(x)

        xyl_gen = XYLike("generator", x, y, yerr)

        pts = PointSource("fake", 0.0, 0.0, function)

        model = Model(pts)

        xyl_gen.set_model(model)

        return xyl_gen.get_simulated_dataset(name)

    @classmethod
    def from_dataframe(cls, name, dataframe, x_column='x', y_column='y', err_column='yerr', poisson=False):
        """
        Generate a XYLike instance from a Pandas.DataFrame instance

        :param name: the name for the XYLike instance
        :param dataframe: the input data frame
        :param x_column: name of the column to be used as x (default: 'x')
        :param y_column: name of the column to be used as y (default: 'y')
        :param err_column: name of the column to be used as error on y (default: 'yerr')
        :param poisson: if True, then the err_column is ignored and data are treated as Poisson distributed
        :return: a XYLike instance
        """

        x = dataframe[x_column]
        y = dataframe[y_column]

        if poisson is False:

            yerr = dataframe[err_column]

            if np.all(yerr == -99):

                # This is a dataframe generate with the to_dataframe method, which uses -99 to indicate that the
                # data are Poisson
                return cls(name, x=x, y=y, poisson=True)

            else:

                # A dataset with errors

                return cls(name, x=x, y=y, yerr=yerr)

        else:

            return cls(name, x=x, y=y, poisson=True)

    @classmethod
    def from_text_file(cls, name, filename):
        """
        Instance the plugin starting from a text file generated with the .to_txt() method. Note that a more general
        way of creating a XYLike instance from a text file is to read the file using pandas.DataFrame.from_csv, and
        then use the .from_dataframe method of the XYLike plugin:

        > df = pd.DataFrame.from_csv(filename, ...)
        > xyl = XYLike.from_dataframe("my instance", df)

        :param name: the name for the new instance
        :param filename: path to the file
        :return:
        """

        df = pd.DataFrame.from_csv(filename, sep=" ")

        return cls.from_dataframe(name, df)

    def to_dataframe(self):
        """
        Returns a pandas.DataFrame instance with the data in the 'x', 'y', and 'yerr' column. If the data are Poisson,
        the yerr column will be -99 for every entry

        :return: a pandas.DataFrame instance
        """

        x_series = pd.Series.from_array(self.x, name='x')
        y_series = pd.Series.from_array(self.y, name='y')

        if self._is_poisson:

            # Since DataFrame does not support metadata, there is no way to save the information that the data
            # are Poisson distributed. We use instead a value of -99 for the error, to indicate that the data
            # are Poisson

            yerr_series = pd.Series.from_array(np.zeros_like(self.x) * (-99), name='yerr')

        else:

            yerr_series = pd.Series.from_array(self.yerr, name='yerr')

        df = pd.concat((x_series, y_series, yerr_series), axis=1)

        return df

    def to_txt(self, filename):
        """
        Save the dataset in a text file. You can read the content back in a dataframe using:

        > df = pandas.DataFrame.from_csv(filename, sep=' ')

        and recreate the XYLike instance as:

        > xyl = XYLike.from_dataframe(df)

        :param filename: Name of the output file
        :return: none
        """

        df = self.to_dataframe()  # type: pd.DataFrame

        df.to_csv(filename, sep=" ")

    def to_csv(self, *args, **kwargs):
        """
        Save the data in a comma-separated-values file (CSV) file. All keywords arguments are passed to the
        pandas.DataFrame.to_csv method (see the documentation from pandas for all possibilities). This gives a very
        high control on the format of the output

        All arguments are forwarded to pandas.DataFrame.to_csv

        :return: none
        """

        df = self.to_dataframe()

        df.to_csv(**kwargs)

    def assign_to_source(self, source_name):
        """
        Assign these data to the given source (instead of to the sum of all sources, which is the default)
        
        :param source_name: name of the source (must be contained in the likelihood model)
        :return: none
        """

        if self._likelihood_model is not None:

            assert self._source_name in self._likelihood_model.sources, "Source %s is not contained in " \
                                                                        "the likelihood model" % source_name

        self._source_name = source_name

    @property
    def x(self):

        return self._x

    @property
    def y(self):

        return self._y

    @property
    def yerr(self):

        return self._yerr

    @property
    def is_poisson(self):

        return self._is_poisson

    @property
    def has_errors(self):

        return self._has_errors

    def set_model(self, likelihood_model_instance):
        """
        Set the model to be used in the joint minimization. Must be a LikelihoodModel instance.

        :param likelihood_model_instance: instance of Model
        :type likelihood_model_instance: astromodels.Model
        """

        if likelihood_model_instance is None:

            return

        if self._source_name is not None:

            # Make sure that the source is in the model
            assert self._source_name in likelihood_model_instance.sources, \
                                                "This XYLike plugin refers to the source %s, " \
                                                "but that source is not in the likelihood model" % (self._source_name)

        self._likelihood_model = likelihood_model_instance

    def _get_total_expectation(self):

        if self._source_name is None:

            n_point_sources = self._likelihood_model.get_number_of_point_sources()

            assert n_point_sources > 0, "You need to have at least one point source defined"
            assert self._likelihood_model.get_number_of_extended_sources() == 0, "XYLike does not support extended sources"

            # Make a function which will stack all point sources (XYLike do not support spatial dimension)

            expectation = np.sum(map(lambda source: source(self._x),
                                 self._likelihood_model.point_sources.values()),
                                 axis=0)

        else:

            # This XYLike dataset refers to a specific source

            # Note that we checked that self._source_name is in the model when the model was set

            try:

                expectation = self._likelihood_model.sources[self._source_name](self._x)

            except KeyError:

                raise KeyError("This XYLike plugin has been assigned to source %s, "
                               "which does not exist in the current model" % self._source_name)

        return expectation

    def get_log_like(self):
        """
        Return the value of the log-likelihood with the current values for the
        parameters
        """

        expectation = self._get_total_expectation()

        if self._is_poisson:

            # Poisson log-likelihood

            return np.sum(poisson_log_likelihood_ideal_bkg(self._y, np.zeros_like(self._y), expectation))

        else:

            # Chi squared
            chi2_ = half_chi2(self._y, self._yerr, expectation)

            assert np.all(np.isfinite(chi2_))

            return np.sum(chi2_) * (-1)

    def get_simulated_dataset(self, new_name=None):

        assert self._has_errors, "You cannot simulate a dataset if the original dataset has no errors"

        self._n_simulated_datasets += 1

        # unmask the data

        old_mask = copy.copy(self._mask)

        self._mask = np.ones(self._x.shape, dtype=bool)


        if new_name is None:

            new_name = "%s_sim%i" % (self.name, self._n_simulated_datasets)

        # Get total expectation from model
        expectation = self._get_total_expectation()

        if self._is_poisson:

            new_y = np.random.poisson(expectation)

        else:

            new_y = np.random.normal(expectation, self._yerr)

        # remask the data BEFORE creating the new plugin

        self._mask = old_mask

        return self._new_plugin(new_name, self._x, new_y, yerr=self._yerr)

    def _new_plugin(self, name, x, y, yerr):
        """
        construct a new plugin. allows for returning a new plugin
        from simulated data set while customizing the constructor
        further down the inheritance tree

        :param name: new name
        :param x: new x
        :param y: new y
        :param yerr: new yerr
        :return: new XYLike


        """

        new_xy = type(self)(name, x, y, yerr, poisson_data=self._is_poisson)

        # apply the current mask

        new_xy._mask = copy.copy(self._mask)

        return new_xy

    def plot(self, x_label='x', y_label='y', x_scale='linear', y_scale='linear',data_color=None,model_color=None,step=False, subplot=None):
        """
        plot the data and the model

        :param x_label: label of x-axis
        :param y_label:  label of y-axis
        :param x_scale: linear or log
        :param y_scale: linear or log
        :param step: True or False to show non-interpolated model
        :param subplot: plot to previous subplot
        :return:
        """

        if subplot is None:

            fig, sub = plt.subplots(1,1)

        else:

            sub = subplot

            fig = subplot.get_figure()

        sub.errorbar(self.x, self.y, yerr=self.yerr, fmt='.',color=data_color)

        sub.set_xscale(x_scale)
        sub.set_yscale(y_scale)

        sub.set_xlabel(x_label)
        sub.set_ylabel(y_label)

        if self._likelihood_model is not None:




            if step:

                x_points = self.x

            else:

                if x_scale == 'linear':

                    x_points = np.linspace(self.x.min(),self.x.max(),len(self.x)*10)

                else:

                    x_points = np.logspace(np.log10(self.x.min()), np.log10(self.x.max()), len(self.x) * 10)

            if self._source_name is None:


                flux = self._likelihood_model.get_total_flux(x_points)

            else:

                flux = self._likelihood_model.sources[self._source_name](x_points)



            sub.plot(x_points, flux, '--', label='model',color=model_color)

            sub.legend(loc=0)

        return fig


    def inner_fit(self):
        """
        This is used for the profile likelihood. Keeping fixed all parameters in the
        LikelihoodModel, this method minimize the logLike over the remaining nuisance
        parameters, i.e., the parameters belonging only to the model for this
        particular detector. If there are no nuisance parameters, simply return the
        logLike value.
        """

        return self.get_log_like()

    def get_model(self):

        return self._get_total_expectation()


    def fit(self, function, minimizer='minuit'):
        """
        Fit the data with the provided function (an astromodels function)

        :param function: astromodels function
        :param minimizer: the minimizer to use
        :return: best fit results
        """

        # This is a wrapper to give an easier way to fit simple data without having to go through the definition
        # of sources
        pts = PointSource("source", 0.0, 0.0, function)

        model = Model(pts)

        self.set_model(model)

        self._joint_like_obj = JointLikelihood(model, DataList(self), verbose=False)

        self._joint_like_obj.set_minimizer(minimizer)

        return self._joint_like_obj.fit()

    def goodness_of_fit(self, n_iterations=1000, continue_of_failure=False):
        """
        Returns the goodness of fit of the performed fit

        :param n_iterations: number of Monte Carlo simulations to generate
        :param continue_of_failure: whether to continue or not if a fit fails (default: False)
        :return: tuple (goodness of fit, frame with all results, frame with all likelihood values)
        """

        g = GoodnessOfFit(self._joint_like_obj)

        return g.by_mc(n_iterations, continue_of_failure)


    def get_number_of_data_points(self):
        """
        returns the number of active data points
        :return:
        """

        # the sum of the mask should be the number of data points in use

        return self._mask.sum()

