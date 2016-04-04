import logging
from numpy import ndarray, arange, amax, amin, size, asarray, random, prod, \
    apply_along_axis

from ..base import Data


class Images(Data):
    """
    Collection of images or volumes

    Backed by an array-like object, including a numpy array
    (for local computation) or a bolt array (for spark computation).

    Attributes
    ----------
    values : array-like
        numpy array or bolt array
    """
    _metadata = Data._metadata

    def __init__(self, values, mode='local'):
        super(Images, self).__init__(values, mode=mode)

    @property
    def _constructor(self):
        return Images

    @property
    def dims(self):
        return self.shape[1:]

    def count(self):
        """
        Explicit count of the number of items.

        For lazy or distributed data, will force a computation.
        """
        if self.mode == 'local':
            return self.shape[0]

        if self.mode == 'spark':
            return self.tordd().count()

    def first(self):
        """
        Return the first element.
        """
        if self.mode == 'local':
            return self.values[0]

        if self.mode == 'spark':
            return self.values.tordd().values().first()

    def toblocks(self, size='150'):
        """
        Convert to Blocks, each representing a subdivision of the larger Images data.

        Parameters
        ----------
        size : str, or tuple of block size per dimension,
            String interpreted as memory size (in megabytes, e.g. "64"). Tuple of ints interpreted as
            "pixels per dimension". Only valid in spark mode.
        """
        from thunder.blocks.blocks import Blocks

        if self.mode == 'spark':
            blocks = self.values.chunk(size).keys_to_values((0,))

        if self.mode == 'local':
            if size != '150':
                logger = logging.getLogger('thunder')
                logger.warn("size has no meaning in Images.toblocks in local mode")
            blocks = self.values

        return Blocks(blocks)

    def totimeseries(self, size='150'):
        """
        Converts this Images object to a TimeSeries object.

        This method is equivalent to images.asBlocks(size).asSeries().asTimeSeries().

        Parameters
        ----------
        size : string memory size, optional, default = "150M"
            String interpreted as memory size (e.g. "64M").

        units : string, either "pixels" or "splits", default = "pixels"
            What units to use for a tuple size.
        """
        return self.toseries(size).totimeseries()

    def toseries(self, size='150'):
        """
        Converts this Images object to a Series object.

        This method is equivalent to images.toblocks(size).toSeries().

        Parameters
        ----------
        size : string memory size, optional, default = "150M"
            String interpreted as memory size (e.g. "64M").
        """
        from thunder.series.series import Series

        n = len(self.shape) - 1
        index = arange(self.shape[0])

        if self.mode == 'spark':
            return Series(self.values.swap((0,), tuple(range(n)), size=size), index=index)

        if self.mode == 'local':
            return Series(self.values.transpose(tuple(range(1, n+1)) + (0,)), index=index)

    def tolocal(self):
        """
        Convert to local representation.
        """
        from thunder.images.readers import fromarray

        if self.mode == 'local':
            logging.getLogger('thunder').warn('images already in local mode')
            pass

        return fromarray(self.toarray())

    def tospark(self, engine=None):
        """
        Convert to spark representation.
        """
        from thunder.images.readers import fromarray

        if self.mode == 'spark':
            logging.getLogger('thunder').warn('images already in spark mode')
            pass

        if engine is None:
            raise ValueError("Must provide a SparkContext")

        return fromarray(self.toarray(), engine=engine)

    def foreach(self, func):
        """
        Execute a function on each image
        """
        if self.mode == 'spark':
            self.values.tordd().map(lambda kv: (kv[0][0], kv[1])).foreach(func)
        else:
            [func(kv) for kv in enumerate(self.values)]

    def sample(self, nsamples=100, seed=None):
        """
        Extract random sample of series.

        Parameters
        ----------
        nsamples : int, optional, default = 100
            The number of data points to sample.

        seed : int, optional, default = None
            Random seed.
        """
        if nsamples < 1:
            raise ValueError("number of samples must be larger than 0, got '%g'" % nsamples)

        if seed is None:
            seed = random.randint(0, 2 ** 32)

        if self.mode == 'spark':
            result = asarray(self.values.tordd().values().takeSample(False, nsamples, seed))

        else:
            inds = [int(k) for k in random.rand(nsamples) * self.shape[0]]
            result = asarray([self.values[i] for i in inds])

        return self._constructor(result)

    def map(self, func, dims=None, with_keys=False):
        """
        Map an array -> array function over each image
        """
        return self._map(func, axis=0, value_shape=dims, with_keys=with_keys)

    def filter(self, func):
        """
        Filter images
        """
        return self._filter(func, axis=0)

    def reduce(self, func):
        """
        Reduce over images
        """
        return self._reduce(func, axis=0)

    def mean(self):
        """
        Compute the mean across images
        """
        return self._constructor(self.values.mean(axis=0, keepdims=True))

    def var(self):
        """
        Compute the variance across images
        """
        return self._constructor(self.values.var(axis=0, keepdims=True))

    def std(self):
        """
        Compute the standard deviation across images
        """
        return self._constructor(self.values.std(axis=0, keepdims=True))

    def sum(self):
        """
        Compute the sum across images
        """
        return self._constructor(self.values.sum(axis=0, keepdims=True))

    def max(self):
        """
        Compute the max across images
        """
        return self._constructor(self.values.max(axis=0, keepdims=True))

    def min(self):
        """
        Compute the min across images
        """
        return self._constructor(self.values.min(axis=0, keepdims=True))

    def squeeze(self):
        """
        Remove single-dimensional axes from images.
        """
        axis = tuple(range(1, len(self.shape) - 1)) if prod(self.shape[1:]) == 1 else None
        return self.map(lambda x: x.squeeze(axis=axis))

    def max_projection(self, axis=2):
        """
        Compute maximum projections of images / volumes
        along the specified dimension.

        Parameters
        ----------
        axis : int, optional, default = 2
            Which axis to compute projection along
        """
        if axis >= size(self.dims):
            raise Exception("Axis for projection (%s) exceeds "
                            "image dimensions (%s-%s)" % (axis, 0, size(self.dims)-1))

        newdims = list(self.dims)
        del newdims[axis]
        return self.map(lambda x: amax(x, axis), dims=newdims)

    def max_min_projection(self, axis=2):
        """
        Compute maximum-minimum projections of images / volumes
        along the specified dimension. This computes the sum
        of the maximum and minimum values along the given dimension.

        Parameters
        ----------
        axis : int, optional, default = 2
            Which axis to compute projection along
        """
        if axis >= size(self.dims):
            raise Exception("Axis for projection (%s) exceeds "
                            "image dimensions (%s-%s)" % (axis, 0, size(self.dims)-1))

        newdims = list(self.dims)
        del newdims[axis]
        return self.map(lambda x: amax(x, axis) + amin(x, axis), dims=newdims)

    def subsample(self, factor):
        """
        Downsample an image volume by an integer factor

        Parameters
        ----------
        sample_factor : positive int or tuple of positive ints
            Stride to use in subsampling. If a single int is passed, each dimension of the image
            will be downsampled by this same factor. If a tuple is passed, it must have the same
            dimensionality of the image. The strides given in a passed tuple will be applied to
            each image dimension.
        """
        dims = self.dims
        ndims = len(dims)
        if not hasattr(factor, "__len__"):
            factor = [factor] * ndims
        factor = [int(sf) for sf in factor]

        if any((sf <= 0 for sf in factor)):
            raise ValueError("All sampling factors must be positive; got " + str(factor))

        def roundup(a, b):
            return (a + b - 1) // b

        slices = [slice(0, dims[i], factor[i]) for i in range(ndims)]
        newdims = tuple([roundup(dims[i], factor[i]) for i in range(ndims)])

        return self.map(lambda v: v[slices], dims=newdims)

    def gaussian_filter(self, sigma=2, order=0):
        """
        Spatially smooth images with a gaussian filter.

        Filtering will be applied to every image in the collection.

        Parameters
        ----------
        sigma : scalar or sequence of scalars, default=2
            Size of the filter size as standard deviation in pixels. A sequence is interpreted
            as the standard deviation for each axis. A single scalar is applied equally to all
            axes.

        order : choice of 0 / 1 / 2 / 3 or sequence from same set, optional, default = 0
            Order of the gaussian kernel, 0 is a gaussian, higher numbers correspond
            to derivatives of a gaussian.
        """
        from scipy.ndimage.filters import gaussian_filter

        return self.map(lambda v: gaussian_filter(v, sigma, order), dims=self.dims)

    def uniform_filter(self, size=2):
        """
        Spatially filter images using a uniform filter.

        Filtering will be applied to every image in the collection.

        parameters
        ----------
        size: int, optional, default=2
            Size of the filter neighbourhood in pixels. A sequence is interpreted
            as the neighborhood size for each axis. A single scalar is applied equally to all
            axes.
        """
        return self._image_filter(filter='uniform', size=size)

    def median_filter(self, size=2):
        """
        Spatially filter images using a median filter.

        Filtering will be applied to every image in the collection.

        parameters
        ----------
        size: int, optional, default=2
            Size of the filter neighbourhood in pixels. A sequence is interpreted
            as the neighborhood size for each axis. A single scalar is applied equally to all
            axes.
        """
        return self._image_filter(filter='median', size=size)

    def _image_filter(self, filter=None, size=2):
        """
        Generic function for maping a filtering operation to images or volumes.

        See also
        --------
        Images.uniformFilter
        Images.medianFilter
        """
        from numpy import isscalar
        from scipy.ndimage.filters import median_filter, uniform_filter

        FILTERS = {
            'median': median_filter,
            'uniform': uniform_filter
        }

        func = FILTERS[filter]

        mode = self.mode
        dims = self.dims
        ndims = len(dims)

        if ndims == 3 and isscalar(size) == 1:
            size = [size, size, size]

        if ndims == 3 and size[2] == 0:
            def filter_(im):
                if mode == 'spark':
                    im.setflags(write=True)
                else:
                    im = im.copy()
                for z in arange(0, dims[2]):
                    im[:, :, z] = func(im[:, :, z], size[0:2])
                return im
        else:
            filter_ = lambda x: func(x, size)

        return self.map(lambda v: filter_(v), dims=self.dims)

    def localcorr(self, neighborhood=2):
        """
        Correlate every pixel to the average of its local neighborhood.

        This algorithm computes, for every spatial record, the correlation coefficient
        between that record's series, and the average series of all records within
        a local neighborhood with a size defined by the neighborhood parameter.
        The neighborhood is currently required to be a single integer,
        which represents the neighborhood size in both x and y.

        Parameters
        ----------
        neighborhood : int, optional, default=2
            Size of the correlation neighborhood (in both the x and y directions), in pixels.
        """

        if not isinstance(neighborhood, int):
            raise ValueError("The neighborhood must be specified as an integer.")

        from thunder.images.readers import fromarray, fromrdd
        from numpy import corrcoef, concatenate

        nimages = self.shape[0]

        # Spatially average the original image set over the specified neighborhood
        blurred = self.uniform_filter((neighborhood * 2) + 1)

        # Union the averaged images with the originals to create an
        # Images object containing 2N images (where N is the original number of images),
        # ordered such that the first N images are the averaged ones.
        if self.mode == 'spark':
            combined = self.values.concatenate(blurred.values)
            combinedImages = fromrdd(combined.tordd())
        else:
            combined = concatenate((self.values, blurred.values), axis=0)
            combinedImages = fromarray(combined)

        # Correlate the first N (averaged) records with the last N (original) records
        series = combinedImages.toseries()
        corr = series.map(lambda x: corrcoef(x[:nimages], x[nimages:])[0, 1])

        return corr.toarray()

    def subtract(self, val):
        """
        Subtract a constant value or an image / volume from
        all images / volumes in the data set.

        Parameters
        ----------
        val : int, float, or ndarray
            Value to subtract
        """
        if isinstance(val, ndarray):
            if val.shape != self.dims:
                raise Exception('Cannot subtract image with dimensions %s '
                                'from images with dimension %s' % (str(val.shape), str(self.dims)))

        return self.map(lambda x: x - val, dims=self.dims)

    def topng(self, path, prefix="image", overwrite=False):
        """
        Write 2d or 3d images as PNG files.

        Files will be written into a newly-created directory.
        Three-dimensional data will be treated as RGB channels.

        Parameters
        ----------
        path : string
            Path to output directory, must be one level below an existing directory.

        prefix : string
            String to prepend to filenames.

        overwrite : bool
            If true, the directory given by path will first be deleted if it exists.
        """
        from thunder.images.writers import topng
        # TODO add back colormap and vmin/vmax
        topng(self, path, prefix=prefix, overwrite=overwrite)

    def totif(self, path, prefix="image", overwrite=False):
        """
        Write 2d or 3d images as TIF files.

        Files will be written into a newly-created directory.
        Three-dimensional data will be treated as RGB channels.

        Parameters
        ----------
        path : string
            Path to output directory, must be one level below an existing directory.

        prefix : string
            String to prepend to filenames.

        overwrite : bool
            If true, the directory given by path will first be deleted if it exists.
        """
        from thunder.images.writers import totif
        # TODO add back colormap and vmin/vmax
        totif(self, path, prefix=prefix, overwrite=overwrite)

    def tobinary(self, path, prefix="image", overwrite=False):
        """
        Write out images or volumes as flat binary files.

        Files will be written into a newly-created directory.

        Parameters
        ----------
        path : string
            Path to output directory, must be one level below an existing directory.

        prefix : string
            String to prepend to filenames.

        overwrite : bool
            If true, the directory given by path will first be deleted if it exists.
        """
        from thunder.images.writers import tobinary
        tobinary(self, path, prefix=prefix, overwrite=overwrite)

    def map_as_series(self, func, value_size=None, block_size='150'):
        """
        Efficiently apply a function to each time series

        Applies a function to each time series without transforming all the way
        to a Series object, but using a Blocks object instead for increased
        efficiency in the transformation back to Images.

        func : function
            Function to apply to each time series. Should take one-dimensional
            ndarray and return the transformed one-dimensional ndarray.

        value_size : int, optional, default=None
            Size of the one-dimensional ndarray resulting from application of
            func. If not supplied, will be automatically inferred for an extra
            computational cost.

        block_size : str, or tuple of block size per dimension,
            String interpreted as memory size (in megabytes e.g. "64"). Tuple of
            ints interpreted as "pixels per dimension".
        """
        blocks = self.toblocks(size=block_size)

        if value_size is not None:
            dims = list(blocks.blockshape)
            dims[0] = value_size
        else:
            dims = None

        def f(block):
            return apply_along_axis(func, 0, block)

        return blocks.map(f, dims=dims).toimages()
