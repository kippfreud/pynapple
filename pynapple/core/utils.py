# -*- coding: utf-8 -*-
# @Author: Guillaume Viejo
# @Date:   2024-02-09 11:45:45
# @Last Modified by:   Guillaume Viejo
# @Last Modified time: 2024-04-04 17:04:38

"""
    Utility functions
"""

import warnings
from itertools import combinations

import numpy as np
from numba import jit

from .config import nap_config


def is_array_like(obj):
    """
    Check if an object is array-like.

    This function determines if an object has array-like properties.
    An object is considered array-like if it has attributes typically associated with arrays
    (such as `.shape`, `.dtype`, and `.ndim`), supports indexing, and is iterable.

    Parameters
    ----------
    obj : object
        The object to check for array-like properties.

    Returns
    -------
    bool
        True if the object is array-like, False otherwise.

    Notes
    -----
    This function uses a combination of checks for attributes (`shape`, `dtype`, `ndim`),
    indexability, and iterability to determine if the given object behaves like an array.
    It is designed to be flexible and work with various types of array-like objects, including
    but not limited to NumPy arrays and JAX arrays. However, it may not be full proof for all
    possible array-like types or objects that mimic these properties without being suitable for
    numerical operations.

    """
    # Check for array-like attributes
    has_shape = hasattr(obj, "shape")
    has_dtype = hasattr(obj, "dtype")
    has_ndim = hasattr(obj, "ndim")

    # Check for indexability (try to access the first element)
    try:
        obj[0]
        is_indexable = True
    except (TypeError, IndexError):
        is_indexable = False

    # Check for iterable property
    try:
        iter(obj)
        is_iterable = True
    except TypeError:
        is_iterable = False

    # not_tsd_type = not isinstance(obj, _AbstractTsd)

    return (
        has_shape
        and has_dtype
        and has_ndim
        and is_indexable
        and is_iterable
        # and not_tsd_type
    )


def convert_to_numpy(array, array_name):
    """
    Convert an input array-like object to a NumPy array.

    This function attempts to convert an input object to a NumPy array using `np.asarray`.
    If the input is not already a NumPy ndarray, it issues a warning indicating that a conversion
    has taken place and shows the original type of the input. This function is useful for
    ensuring compatibility with Numba operations in cases where the input might come from
    various array-like sources (for instance, jax.numpy.Array).

    Parameters
    ----------
    array : array_like
        The input object to convert. This can be any object that `np.asarray` is capable of
        converting to a NumPy array, such as lists, tuples, and other array-like objects,
        including those from libraries like JAX or TensorFlow that adhere to the array interface.
    array_name : str
        The name of the variable that we are converting, printed in the warning message.

    Returns
    -------
    ndarray
        A NumPy ndarray representation of the input `values`. If `values` is already a NumPy
        ndarray, it is returned unchanged. Otherwise, a new NumPy ndarray is created and returned.

    Warnings
    --------
    A warning is issued if the input `values` is not already a NumPy ndarray, indicating
    that a conversion has taken place and showing the original type of the input.

    """
    if (
        not isinstance(array, np.ndarray)
        and not nap_config.suppress_conversion_warnings
    ):
        original_type = type(array).__name__
        warnings.warn(
            f"Converting '{array_name}' to numpy.array. The provided array was of type '{original_type}'.",
            UserWarning,
        )
    return np.asarray(array)


def _check_time_equals(time_arrays):
    """
    Check if a list of time arrays are all equal.
    This is typically use to compare time index arrays or starts and ends of `IntervalSet`

    Parameters
    ----------
    time_arrays : list
        The time arrays to compare to each other

    Returns
    -------
    bool
        True if all equal else False

    """
    return all(
        map(
            lambda x: np.allclose(
                *x, rtol=0, atol=1 / (10**nap_config.time_index_precision)
            ),
            combinations(time_arrays, 2),
        )
    )


def _split_tsd(func, tsd, indices_or_sections, axis=0):
    """
    Wrappers of numpy split functions
    """
    if func in [np.split, np.array_split, np.vsplit] and axis == 0:
        out = func._implementation(tsd.values, indices_or_sections)
        index_list = np.split(tsd.index.values, indices_or_sections)
        kwargs = {"columns": tsd.columns.values} if hasattr(tsd, "columns") else {}
        return [tsd.__class__(t=t, d=d, **kwargs) for t, d in zip(index_list, out)]
    elif func in [np.dsplit, np.hsplit]:
        out = func._implementation(tsd.values, indices_or_sections)
        kwargs = {"columns": tsd.columns.values} if hasattr(tsd, "columns") else {}
        return [tsd.__class__(t=tsd.index, d=d, **kwargs) for d in out]
    else:
        return func._implementation(tsd.values, indices_or_sections, axis)


def _concatenate_tsd(func, *args, **kwargs):
    """
    Wrappers of concatenation functions
    """
    arrays = []
    time_indexes = []
    time_supports = []
    nap_types = []
    columns = []
    nap_class = None

    if func == np.concatenate:  # search for axis
        if "axis" not in kwargs and len(args) >= 2:  # assume second arg is axis
            if isinstance(args[1], int):
                kwargs["axis"] = args[1]
            else:
                kwargs["axis"] = 0

    for arg in args[0]:
        if all(
            map(
                lambda x: hasattr(arg, x),
                ["values", "index", "time_support", "nap_class"],
            )
        ):
            arrays.append(arg.values)
            time_indexes.append(arg.index.values)
            time_supports.append(arg.time_support)
            nap_types.append(arg.nap_class)
            nap_class = arg.__class__
            if hasattr(arg, "columns"):
                columns.append(arg.columns)
        else:
            arrays.append(arg)

    output = func._implementation(arrays, **kwargs)

    # dimension increased in the first axis
    if output.shape[0] > arrays[0].shape[0]:
        if len(time_indexes) == len(arrays) and len(time_supports) == len(arrays):
            # check if time indexes can be concatenated
            new_index = np.hstack(time_indexes)
            if np.any(np.diff(new_index) <= 0):
                raise RuntimeError(
                    "The order of the time series indexes should be strictly increasing and non overlapping."
                )
            # Joining Time support
            time_support = time_supports[0]
            for support in time_supports[1:]:
                time_support = time_support.union(support)

            new_kwargs = {"columns": columns[0]} if len(columns) else {}

            return nap_class(
                t=new_index, d=output, time_support=time_support, **new_kwargs
            )
        else:
            return output
    # dimension increased in other axis
    else:
        if len(time_indexes) == 1:
            return nap_class(t=time_indexes[0], d=output, time_support=time_supports[0])
        else:
            time_equal = _check_time_equals(time_indexes)
            support_equal = _check_time_equals([x.values for x in time_supports])

            if time_equal and support_equal:
                return nap_class(
                    t=time_indexes[0], d=output, time_support=time_supports[0]
                )
            else:
                if not time_equal and not support_equal:
                    msg = "Time indexes and time supports are not all equals up to pynapple precision. Returning numpy array!"
                elif not time_equal and support_equal:
                    msg = "Time indexes are not all equals up to pynapple precision. Returning numpy array!"
                else:
                    msg = "Time supports are not all equals up to pynapple precision. Returning numpy array!"

                warnings.warn(msg, stacklevel=2)
                return output


@jit(nopython=True)
def _jitfix_iset(start, end):
    """
    0 - > "Some starts and ends are equal. Removing 1 microsecond!",
    1 - > "Some ends precede the relative start. Dropping them!",
    2 - > "Some starts precede the previous end. Joining them!",
    3 - > "Some epochs have no duration"

    Parameters
    ----------
    start : numpy.ndarray
        Description
    end : numpy.ndarray
        Description

    Returns
    -------
    TYPE
        Description
    """
    to_warn = np.zeros(4, dtype=np.bool_)
    m = start.shape[0]
    data = np.zeros((m, 2), dtype=np.float64)
    i = 0
    ct = 0

    while i < m:
        newstart = start[i]
        newend = end[i]

        while i < m:
            if end[i] == start[i]:
                to_warn[3] = True
                i += 1
            else:
                newstart = start[i]
                newend = end[i]
                break

        while i < m:
            if end[i] < start[i]:
                to_warn[1] = True
                i += 1
            else:
                newstart = start[i]
                newend = end[i]
                break

        if i >= m:
            break

        while i < m - 1:
            if start[i + 1] < end[i]:
                to_warn[2] = True
                i += 1
                newend = max(end[i - 1], end[i])
            else:
                break

        if i < m - 1:
            if newend == start[i + 1]:
                to_warn[0] = True
                newend -= 1.0e-6

        data[ct, 0] = newstart
        data[ct, 1] = newend

        ct += 1
        i += 1

    data = data[0:ct]

    return (data, to_warn)


class _TsdFrameSliceHelper:
    def __init__(self, tsdframe):
        self.tsdframe = tsdframe

    def __getitem__(self, key):
        if hasattr(key, "__iter__") and not isinstance(key, str):
            for k in key:
                if k not in self.tsdframe.columns:
                    raise IndexError(str(k))
            index = self.tsdframe.columns.get_indexer(key)
        else:
            if key not in self.tsdframe.columns:
                raise IndexError(str(key))
            index = self.tsdframe.columns.get_indexer([key])

        if len(index) == 1:
            return self.tsdframe.__getitem__((slice(None, None, None), index[0]))
        else:
            return self.tsdframe.__getitem__(
                (slice(None, None, None), index), columns=key
            )


class _IntervalSetSliceHelper:
    """
    This class helps `IntervalSet` behaves like pandas.DataFrame for the `loc` function.

    Attributes
    ----------
    intervalset : `IntervalSet` to slice

    """

    def __init__(self, intervalset):
        """Class for `loc` slicing function

        Parameters
        ----------
        intervalset : IntervalSet

        """
        self.intervalset = intervalset

    def __getitem__(self, key):
        """Getters for `IntervalSet.loc`. Mimics pandas.DataFrame.

        Parameters
        ----------
        key : int, list or tuple

        Returns
        -------
        IntervalSet or Number or numpy.ndarray

        Raises
        ------
        IndexError

        """
        if key in ["start", "end"]:
            return self.intervalset[key]
        elif isinstance(key, list):
            return self.intervalset[key]
        elif isinstance(key, int):
            return self.intervalset.values[key]
        else:
            if isinstance(key, tuple):
                if len(key) == 2:
                    if key[1] not in ["start", "end"]:
                        raise IndexError
                    out = self.intervalset[key[0]][key[1]]
                    if len(out) == 1:
                        return out[0]
                    else:
                        return out
                else:
                    raise IndexError
            else:
                raise IndexError
