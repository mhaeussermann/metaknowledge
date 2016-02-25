#Written by Reid McIlroy-Young for Dr. John McLevey, University of Waterloo 2015
import itertools
import os
import csv
import pickle
import collections.abc
import copy

import networkx as nx

from .constants import __version__
from .record import Record
from .progressBar import _ProgressBar
from .WOS.tagProcessing.funcDicts import tagToFullDict, fullToTagDict, normalizeToTag
from .citation import Citation
from .mkExceptions import cacheError, BadWOSFile, BadWOSRecord, RCTypeError, BadInputFile, BadRecord, RCValueError, RecordsNotCompatible

from .WOS.wosHandlers import wosParser, isWOSFile

from .medline.medlineHandlers import medlineParser, isMedlineFile

import metaknowledge

class RecordCollection(collections.abc.MutableSet, collections.abc.Hashable):
    """
    A container for a large number of indivual WOS records.

    `RecordCollection` provides ways of creating `[Records`](#metaknowledge.Record) from an isi file, string, list of records or directory containing isi files.

    When being created if there are issues the Record collection will be declared bad, `bad` wil be set to `False`, it will then mostly return `None` or False. The attribute `error` contains the exception that occurred.

    They also possess an attribute `name` also accessed accessed with **__repr__**(), this is used to auto generate the names of files and can be set at creation, note though that any operations that modify the RecordCollection's contents will update the name to include what occurred.

    # Customizations

    The Records are containing within a set and as such many of the set operations are defined, pop, union, in ... also records are hashed with their WOS string so no duplication can occur. The comparison operators `<`, `<=`, `>`, `>=` are based strictly on the number of Records within the collection, while equality looks for an exact match on the Records

    # \_\_Init\_\_

    _inCollection_ is the object containing the information about the Records to be constructed it can be an isi file, string, list of records or directory containing isi files

    # Parameters

    _inCollection_ : `optional [str] or None`

    > the name of the source of WOS records. It can be skipped to produce an empty collection.

    > If a file is provided. First it is checked to see if it is a WOS file (the header is checked). Then records are read from it one by one until the 'EF' string is found indicating the end of the file.

    > If a directory is provided. First each file in the directory is checked for the correct header and all those that do are then read like indivual files. The records are then collected into a single set in the RecordCollection.

    _name_ : `optional [str]`

    > The name of the RecordCollection, defaults to empty string. If left empty the name of the Record collection is set to the name of the file or directory used to create the collection. If provided the name id set to _name_

    _extension_ : `optional [str]`

    > The extension to search for when reading a directory for files. _extension_ is the suffix searched for when a directory is read for files, by default it is empty so all files are read.

    _cached_ : `optional [bool]`

    > Default `False`, if `True` and the _inCollection_ is a directory (a string giving the path to a directory) then the initialized `RecordCollection` will be saved in the directory as a Python pickle with the suffix `'.mkDirCache'`. Then if the `RecordCollection` is initialized a second time it will be recovered from the file, which is much faster than reprising every file in the directory.

    > _metaknowledge_ saves the names of the parsed files as well as their last modification times and will check these when recreating the `RecordCollection`, so modifying existing files or adding new ones will result in the entire directory being reanalyzed and a new cache file being created. The extension given to **__init__**() is taken into account as well and each suffix is given its own cache.

    > **Note** The pickle allows for arbitrary python code exicution so only use caches that you trust.
    """

    def __init__(self, inCollection = None, name = '', extension = '', cached = False, quietStart = False):
        progArgs = (0, "Starting to make a RecordCollection")
        if metaknowledge.VERBOSE_MODE and not quietStart:
            progKwargs = {'dummy' : False}
        else:
            progKwargs = {'dummy' : True}
        with _ProgressBar(*progArgs, **progKwargs) as PBar:
            self.bad = False
            self.errors = {}
            self.name = name
            self.recordTypes = set()
            if inCollection is None:
                PBar.updateVal(.5, "Empty RecordCollection created")
                if not name:
                    self.name = "Empty"
                self._Records = set()
            elif isinstance(inCollection, str):
                if os.path.isfile(inCollection):
                    PBar.updateVal(.5, "RecordCollection from a file started")
                    if not inCollection.endswith(extension):
                        raise RCTypeError("extension of input file does not match requested extension")
                    if not name:
                        self.name = os.path.splitext(os.path.split(inCollection)[1])[0]
                    if isWOSFile(inCollection):
                        self.recordTypes.add('WOS')
                        self._Records, pError = wosParser(inCollection)
                        if pError is not None:
                            self.bad = True
                            self.errors[inCollection] = pError
                    elif isMedlineFile(inCollection):
                        self.recordTypes.add('MEDLINE')
                        self._Records, pError = medlineParser(inCollection)
                        if pError is not None:
                            self.bad = True
                            self.errors[inCollection] = pError
                    else:
                        raise BadInputFile("'{}' does not match any known file type. Its header might be damaged or it could have been modified by another program.".format(inCollection))
                elif os.path.isdir(inCollection):
                    count = 0
                    PBar.updateVal(0, "RecordCollection from a files in {}".format(inCollection))
                    if extension and not name:
                        self.name = "{}-files-from-{}".format(extension, inCollection)
                    elif not name:
                        self.name = "files-from-{}".format(inCollection)
                    self._Records = set()
                    flist = []
                    for f in os.listdir(inCollection):
                        fullF = os.path.join(os.path.abspath(inCollection), f)
                        if fullF.endswith(extension) and not fullF.endswith('mkDirCache') and os.path.isfile(fullF):
                            flist.append(fullF)
                    if cached:
                        cacheName = os.path.join(inCollection, '{}.[{}].mkDirCache'.format(os.path.basename(os.path.abspath(inCollection)), extension))
                        if os.path.isfile(cacheName):
                            try:
                                self.__dict__ = loadCache(cacheName, flist, name, extension, PBar).__dict__
                            except cacheError:
                                PBar.updateVal(0, 'Cache error, rereading files')
                                os.remove(cacheName)
                            else:
                                PBar.finish("Done reloading {} Records from cache".format(len(self)))
                                return
                    for fileName in flist:
                        count += 1
                        PBar.updateVal(count / len(flist), "Reading records from: {}".format(fileName))
                        if isWOSFile(fileName):
                            if 'WOS' not in self.recordTypes:
                                self.recordTypes.add('WOS')
                            recs, pError = wosParser(fileName)
                            if pError is not None:
                                self.bad = True
                                self.errors[fileName]= pError
                            self._Records |= recs
                        elif isMedlineFile(fileName):
                            if 'MEDLINE' not in self.recordTypes:
                                self.recordTypes.add('MEDLINE')
                            recs, pError = medlineParser(fileName)
                            if pError is not None:
                                self.bad = True
                                self.errors[fileName]= pError
                            self._Records |= recs
                        elif extension != '':
                            raise BadInputFile("'{}' does not match any known file type, but has the requested extension '{}'. Its header might be damaged or it could have been modified by another program.".format(fileName, extension))
                        else:
                            pass
                    if cached:
                        writeCache(self, cacheName, flist, name, extension, PBar)
                else:
                    raise RCTypeError("'{}' is not a path to a directory or file. Strings cannot be used to initialize RecordCollections".format(inCollection))
            elif isinstance(inCollection, collections.abc.Iterable):
                PBar.updateVal(.5, "RecordCollection from an iterable started")
                for R in inCollection:
                    if not isinstance(R, Record):
                        raise RCTypeError("RecordCollections can only contain Records, '{}' is not a valid part of an input iterable.".format(R))
                self._Records = set(inCollection)
            else:
                raise RCTypeError("RecordCollection cannot be created from {}.".format(inCollection))
            try:
                PBar.finish("Done making a RecordCollection of {} Records".format(len(self)))
            except AttributeError:
                PBar.finish("Done making a RecordCollection. Warning an error occured.")

    #Hashable method

    def __hash__(self):
        return hash(sum((hash(R) for R in self)))

    #Set methods

    def __le__(self, other):
        if not isinstance(other, RecordCollection):
            return NotImplemented
        else:
            return len(self) <= len(other)

    def __ge__(self, other):
        if not isinstance(other, RecordCollection):
            return NotImplemented
        else:
            return len(self) >= len(other)

    def __eq__(self, other):
        if not isinstance(other, RecordCollection):
            return NotImplemented
        else:
            return self._Records == other._Records

    def __len__(self):
        """
        returns the number or Records
        """
        return len(self._Records)

    def __iter__(self):
        """
        iterates over the Records
        """
        for R in self._Records:
            yield R

    def __contains__(self, item):
        return item in self._Records

    #Mutable Set methods

    def add(self, elem):
        if isinstance(elem, Record):
            self._Records.add(elem)
        else:
            raise RCTypeError("recordCollections can only contain Records, '{}' is not a Record.".format(elem))

    def discard(self, elem):
        return self._Records.discard(elem)

    def remove(self, elem):
        try:
            return self._Records.remove(elem)
        except KeyError:
            raise KeyError("'{}' was not found in the RecordCollection: '{}'.".format(elem, self)) from None

    def clear(self):
        self.bad = False
        self.errors = {}
        self._Records.clear()

    def pop(self):
        try:
            return self._Records.pop()
        except KeyError:
            raise KeyError("No more Records in the RecordCollection: '{}'.".format(self)) from None

    def __ior__(self, other):
        if not isinstance(other, RecordCollection):
            return NotImplemented
        else:
            self._Records |= other._Records
            if other.bad or self.bad:
                self.bad = True
                self.errors.update(other.errors)
            return self

    def __iand__(self, other):
        if not isinstance(other, RecordCollection):
            return NotImplemented
        else:
            self._Records &= other._Records
            if other.bad or self.bad:
                self.bad = True
                self.errors.update(other.errors)
            return self

    def __ixor__(self, other):
        if not isinstance(other, RecordCollection):
            return NotImplemented
        else:
            self._Records ^= other._Records
            if other.bad or self.bad:
                self.bad = True
                self.errors.update(other.errors)
            return self

    def __isub__(self, other):
        if not isinstance(other, RecordCollection):
            return NotImplemented
        else:
            self._Records -= other._Records
            if other.bad or self.bad:
                self.bad = True
                self.errors.update(other.errors)
            return self

    #These are provided by the above
    #but don't work right unless they are custom writen

    def __or__(self, other):
        if not isinstance(other, RecordCollection):
            return NotImplemented
        else:
            retRC = RecordCollection(self._Records | other._Records, name = '{} | {}'.format(self, other), quietStart = True)
            if other.bad or self.bad:
                retRC.bad = True
                retRC.errors.update(other.errors)
            return retRC

    def __and__(self, other):
        if not isinstance(other, RecordCollection):
            return NotImplemented
        else:
            retRC = RecordCollection(self._Records & other._Records, name = '{} & {}'.format(self, other), quietStart = True)
            if other.bad or self.bad:
                retRC.bad = True
                retRC.errors.update(other.errors)
            return retRC

    def __sub__(self, other):
        if not isinstance(other, RecordCollection):
            return NotImplemented
        else:
            retRC = RecordCollection(self._Records - other._Records, name = '{} - {}'.format(self, other), quietStart = True)
            if other.bad or self.bad:
                retRC.bad = True
                retRC.errors.update(other.errors)
            return retRC

    def __xor__(self, other):
        if not isinstance(other, RecordCollection):
            return NotImplemented
        else:
            retRC = RecordCollection(self._Records ^ other._Records, name = '{} ^ {}'.format(self, other), quietStart = True)
            if other.bad or self.bad:
                retRC.bad = True
                retRC.errors.update(other.errors)
            return retRC

    #Other niceties

    def __repr__(self):
        return "<metaknowledge.{} object {}>".format(type(self).__name__, self.name)

    def __str__(self):
        return "RecordCollection({})".format(self.name)

    def __bytes__(self):
        encoding = self.peak().encoding
        try:
            return bytes('\n', encoding = encoding).join((bytes(R) for R in self))
        except BadRecord as e:
            raise e from None

    def copy(self):
        rcCopy = copy.copy(self)
        rcCopy._Records = rcCopy._Records.copy()
        rcCopy.errors = rcCopy.errors.copy()
        return rcCopy

    def containsID(self, idVal):
        for R in self:
            if R.id == idVal:
                return True
        return False

    def peak(self):
        """
        Returns a random `Record` from the `RecordCollection`, the `Record` is kept in the collection, use [**pop**()](#recordCollection.pop) for faster destructive access.

        # Returns

        `Record`

        > A random `Record` in the collection
        """
        if len(self._Records) > 0:
            return self._Records.__iter__().__next__()
        else:
            return None

    def discardID(self, idVal):
        for R in self:
            if R.id == idVal:
                self._Records.discard(R)
                return

    def removeID(self, idVal):
        for R in self:
            if R.id == idVal:
                self._Records.remove(R)
                return
        raise KeyError("A Record with the ID '{}' was not found in the RecordCollection: '{}'.".format(idVal, self))

    def getID(self, idVal):
        for R in self:
            if R.id == idVal:
                return R
        return None

    def BadRecords(self):
        """creates a `RecordCollection` containing all the `Record` which have their `bad` attribute set to `True`, i.e. all those removed by [**dropBadRecords**()](#RecordCollection.dropBadRecords).

        # Returns

        `RecordCollection`

        > All the bad `Records` in one collection
        """
        badRecords = set()
        for R in self._Records:
            if R.bad:
                badRecords.add(R)
        return RecordCollection(badRecords, repr(self) + '_badRecords', quietStart = True)

    def dropBadRecords(self):
        """Removes all `Records` with `bad` attribute `True` from the collection, i.e. drop all those returned by [**BadRecords**()](#RecordCollection.BadRecords).
        """
        self._Records = {r for r in self._Records if not r.bad}

    def dropNonJournals(self, ptVal = 'J', dropBad = True, invert = False):
        """Drops the non journal type `Records` from the collection, this is done by checking _ptVal_ against the PT tag

        # Parameters

        _ptVal_ : `optional [str]`

        > Default `'J'`, The value of the PT tag to be kept, default is `'J'` the journal tag, other tags can be substituted.

        _dropBad_ : `optional [bool]`

        > Default `True`, if `True` bad `Records` will be dropped as well those that are not journal entries

        _invert_ : `optional [bool]`

        > Default `False`, Set `True` to drop journals (or the PT tag given by _ptVal_) instead of keeping them. **Note**, it still drops bad Records if _dropBad_ is `True`
        """
        if dropBad:
            self.dropBadRecords()
        if invert:
            self._Records = {r for r in self._Records if r['pubType'] != ptVal.upper()}
        else:
            self._Records = {r for r in self._Records if r['pubType'] == ptVal.upper()}

    def writeFile(self, fname = None):
        """Writes the `RecordCollection` to a file, the written file's format is identical to those download from WOS. The order of `Records` written is random.

        # Parameters

        _fname_ : `optional [str]`

        > Default `None`, if given the output file will written to _fanme_, if `None` the `RecordCollection`'s name's first 200 characters are used with the suffix .isi
        """
        if len(self.recordTypes) < 2:
            recEncoding = self.peak().encoding
        else:
            recEncoding = 'utf-8'
        if fname:
            f = open(fname, mode = 'w', encoding = recEncoding)
        else:
            f = open(self.name[:200] + '.txt', mode = 'w', encoding = recEncoding)
        if self.recordTypes == {'WOS'}:
            f.write("\ufeffFN Thomson Reuters Web of Science\u2122\n")
            f.write("VR 1.0\n")
        elif self.recordTypes == {'MEDLINE'}:
            f.write('\n')
        for R in self._Records:
            R.writeRecord(f)
            f.write('\n')
        if self.recordTypes == {'WOS'}:
            f.write('EF')
        f.close()

    def writeCSV(self, fname = None, onlyTheseTags = None, numAuthors = True, longNames = False, firstTags = None, csvDelimiter = ',', csvQuote = '"', listDelimiter = '|'):
        """Writes all the `Records` from the collection into a csv file with each row a record and each column a tag.

        # Parameters

        _fname_ : `optional [str]`

        > Default `None`, the name of the file to write to, if `None` it uses the collections name suffixed by .csv.

        _onlyTheseTags_ : `optional [iterable]`

        > Default `None`, if an iterable (list, tuple, etc) only the tags in _onlyTheseTags_ will be used, if not given then all tags in the records are given.

        > If you want to use all known tags pass [`metaknowledge.knownTagsList`](#metaknowledge.tagProcessing).

        _numAuthors_ : `optional [bool]`

        > Default `True`, if `True` adds the number of authors as the column `'numAuthors'`.

        _longNames_ : `optional [bool]`

        > Default `False`, if `True` will convert the tags to their longer names, otherwise the short 2 character ones will be used.

        _firstTags_ : `optional [iterable]`

        > Default `None`, if `None` the iterable `['UT', 'PT', 'TI', 'AF', 'CR']` is used. The tags given by the iterable are the first ones in the csv in the order given.

        > **Note** if tags are in _firstTags_ but not in _onlyTheseTags_, _onlyTheseTags_ will override _firstTags_

        _csvDelimiter_ : `optional [str]`

        > Default `','`, the delimiter used for the cells of the csv file.

        _csvQuote_ : `optional [str]`

        > Default `'"'`, the quote character used for the csv.

        _listDelimiter_ : `optional [str]`

        > Default `'|'`, the delimiter used between values of the same cell if the tag for that record has multiple outputs.
        """
        if firstTags is None:
            firstTags = ['UT', 'PT', 'TI', 'AF', 'CR']
        for i in range(len(firstTags)):
            if firstTags[i] in fullToTagDict:
                firstTags[i] = fullToTagDict[firstTags[i]]
        if onlyTheseTags:
            for i in range(len(onlyTheseTags)):
                if onlyTheseTags[i] in fullToTagDict:
                    onlyTheseTags[i] = fullToTagDict[onlyTheseTags[i]]
            retrievedFields = [t for t in firstTags if t in onlyTheseTags] + [t for t in onlyTheseTags if t not in firstTags]
        else:
            retrievedFields = firstTags
            for R in self:
                tagsLst = [t for t in R.keys() if t not in retrievedFields]
                retrievedFields += tagsLst
        if longNames:
            try:
                retrievedFields = [tagToFullDict[t] for t in retrievedFields]
            except KeyError:
                raise KeyError("One of the tags could not be converted to a long name.")
        if fname:
            f = open(fname, mode = 'w', encoding = 'utf-8')
        else:
            f = open(self.name[:200] + '.csv', mode = 'w', encoding = 'utf-8')
        if numAuthors:
            csvWriter = csv.DictWriter(f, retrievedFields + ["numAuthors"], delimiter = csvDelimiter, quotechar = csvQuote, quoting=csv.QUOTE_ALL)
        else:
            csvWriter = csv.DictWriter(f, retrievedFields, delimiter = csvDelimiter, quotechar = csvQuote, quoting=csv.QUOTE_ALL)
        csvWriter.writeheader()
        for R in self:
            recDict = R.subDict(retrievedFields)
            if numAuthors:
                recDict["numAuthors"] = len(R['authorsShort'])
            for k in recDict.keys():
                value = recDict[k]
                if hasattr(value, '__iter__'):
                    recDict[k] = listDelimiter.join([str(v) for v in value])
                elif recDict[k] == None:
                    recDict[k] = ''
                else:
                    recDict[k] = str(value)
            csvWriter.writerow(recDict)
        f.close()

    def writeBib(self, fname = None, maxStringLength = 1000, wosMode = False, reducedOutput = False, niceIDs = True):
        """Writes a bibTex entry to _fname_ for each `Record` in the collection.

        If the Record is of a journal article (PT J) the bibtext type is set to `'article'`, otherwise it is set to `'misc'`. The ID of the entry is the WOS number and all the Record's fields are given as entries with their long names.

        **Note** This is not meant to be used directly with LaTeX none of the special characters have been escaped and there are a large number of unnecessary fields provided. _niceID_ and _maxLength_ have been provided to make conversions easier only.

        **Note** Record entries that are lists have their values separated with the string `' and '`, as this is the way bibTex understands

        # Parameters

        _fname_ : `optional [str]`

        > Default `None`, The name of the file to be written. If not given one will be derived from the collection and the file will be written to .

        _maxStringLength_ : `optional [int]`

        > Default 1000, The max length for a continuous string. Most bibTex implementation only allow string to be up to 1000 characters ([source](https://www.cs.arizona.edu/~collberg/Teaching/07.231/BibTeX/bibtex.html)), this splits them up into substrings then uses the native string concatenation (the `'#'` character) to allow for longer strings

        _WOSMode_ : `optional [bool]`

        > Default `False`, if `True` the data produced will be unprocessed and use double curly braces. This is the style WOS produces bib files in and mostly macthes that.

        _restrictedOutput_ : `optional [bool]`

        > Default `False`, if `True` the tags output will be limited to: `'AF'`, `'BF'`, `'ED'`, `'TI'`, `'SO'`, `'LA'`, `'NR'`, `'TC'`, `'Z9'`, `'PU'`, `'J9'`, `'PY'`, `'PD'`, `'VL'`, `'IS'`, `'SU'`, `'PG'`, `'DI'`, `'D2'`, and `'UT'`

        _niceID_ : `optional [bool]`

        > Default `True`, if `True` the IDs used will be derived from the authors, publishing date and title, if `False` it will be the UT tag
        """
        if fname:
            f = open(fname, mode = 'w', encoding = 'utf-8')
        else:
            f = open(self.name[:200] + '.bib', mode = 'w', encoding = 'utf-8')
        f.write("%This file was generated by the metaknowledge Python package.\n%The contents have been automatically generated and are likely to not work with\n%LaTeX without some human intervention. This file is meant for other automatic\n%systems and not to be used directly for making citations\n")
        #I figure this is worth mentioning, as someone will get annoyed at none of the special characters being escaped and how terrible some of the fields look to humans
        for R in self:
            try:
                f.write('\n\n')
                f.write(R.bibString(maxLength =  maxStringLength, WOSMode = wosMode, restrictedOutput = reducedOutput, niceID = niceIDs))
            except BadWOSRecord:
                pass
            except AttributeError:
                raise RecordsNotCompatible("The Record '{}', with ID '{}' does not support writing to bibtext files.".format(R, R.id))
        f.close()

    def makeDict(self, onlyTheseTags = None, longNames = False, raw = False, numAuthors = True):
        """Returns a dict with each key a tag and the values being lists of the values for each of the Records in the collection, `None` is given when there is no value and they are in the same order across each tag.

        When used with pandas: `pandas.DataFrame(RC.makeDict())` returns a data frame with each column a tag and each row a Record.

        # Parameters

        _onlyTheseTags_ : `optional [iterable]`

        > Default `None`, if an iterable (list, tuple, etc) only the tags in _onlyTheseTags_ will be used, if not given then all tags in the records are given.

        > If you want to use all known tags pass [`metaknowledge.knownTagsList`](#metaknowledge.tagProcessing).

        _longNames_ : `optional [bool]`

        > Default `False`, if `True` will convert the tags to their longer names, otherwise the short 2 character ones will be used.

        _cleanedVal_ : `optional [bool]`

        > Default `True`, if `True` the processed values for each `Record`'s field will be provided, otherwise the raw values are given.

        _numAuthors_ : `optional [bool]`

        > Default `True`, if `True` adds the number of authors as the column `'numAuthors'`.
        """
        if onlyTheseTags:
            for i in range(len(onlyTheseTags)):
                if onlyTheseTags[i] in fullToTagDict:
                    onlyTheseTags[i] = fullToTagDict[onlyTheseTags[i]]
            retrievedFields = onlyTheseTags
        else:
            retrievedFields = []
            for R in self:
                tagsLst = [t for t in R.keys() if t not in retrievedFields]
                retrievedFields += tagsLst
        if longNames:
            try:
                retrievedFields = [tagToFullDict[t] for t in retrievedFields]
            except KeyError:
                raise KeyError("One of the tags could not be converted to a long name.")
        retDict = {k : [] for k in retrievedFields}
        if numAuthors:
            retDict["numAuthors"] = []
        for R in self:
            if numAuthors:
                retDict["numAuthors"].append(len(R.get('authorsShort')))
            for k, v in R.subDict(retrievedFields, raw = raw).items():
                retDict[k].append(v)
        return retDict

    def coAuthNetwork(self, detailedInfo = False, weighted = True, dropNonJournals = False, count = True):
        """Creates a coauthorship network for the RecordCollection.

        # Parameters

        _detailedInfo_ : `optional [bool or iterable[WOS tag Strings]]`

        > Default `False`, if `True` all nodes will be given info strings composed of information from the Record objects themselves. This is Equivalent to passing the list: `['PY', 'TI', 'SO', 'VL', 'BP']`.

        > If _detailedInfo_ is an iterable (that evaluates to `True`) of WOS Tags (or long names) The values  of those tags will be used to make the info attributes.

        > For each of the selected tags an attribute will be added to the node using the values of those tags on the first `Record` encountered. **Warning** iterating over `RecordCollection` objects is not deterministic the first `Record` will not always be same between runs. The node will be given attributes with the names of the WOS tags for each of the selected tags. The attributes will contain strings of containing the values (with commas removed), if multiple values are encountered they will be comma separated.

        > Note: _detailedInfo_ is not identical to the _detailedCore_ argument of [`Recordcollection.coCiteNetwork()`](#RecordCollection.coCiteNetwork) or [`Recordcollection.citationNetwork()`](#RecordCollection.citationNetwork)

        _weighted_ : `optional [bool]`

        > Default `True`, wether the edges are weighted. If `True` the edges are weighted by the number of co-authorships.

        _dropNonJournals_ : `optional [bool]`

        > Default `False`, wether to drop authors from non-journals

        _count_ : `optional [bool]`

        > Default `True`, causes the number of occurrences of a node to be counted

        # Returns

        `Networkx Graph`

        > A networkx graph with author names as nodes and collaborations as edges.
        """
        grph = nx.Graph()
        pcount = 0
        progArgs = (0, "Starting to make a co-authorship network")
        if metaknowledge.VERBOSE_MODE:
            progKwargs = {'dummy' : False}
        else:
            progKwargs = {'dummy' : True}
        if bool(detailedInfo):
            try:
                infoVals = []
                for tag in detailedInfo:
                    infoVals.append(normalizeToTag(tag))
            except TypeError:
                infoVals = ['PY', 'TI', 'SO', 'VL', 'BP']
            def attributeMaker(Rec):
                attribsDict = {}
                for val in infoVals:
                    recVal = Rec.get(val)
                    if isinstance(recVal, list):
                        attribsDict[val] = ', '.join((str(v).replace(',', '') for v in recVal))
                    else:
                        attribsDict[val] = str(recVal).replace(',', '')
                if count:
                    attribsDict['count'] = 1
                return attribsDict
        else:
            if count:
                attributeMaker = lambda x: {'count' : 1}
            else:
                attributeMaker = lambda x: {}
        with _ProgressBar(*progArgs, **progKwargs) as PBar:
            for R in self:
                if PBar:
                    pcount += 1
                    PBar.updateVal(pcount/ len(self), "Analyzing: " + str(R))
                if dropNonJournals and not R.createCitation().isJournal():
                    continue
                authsList = R.get('authorsFull')
                if authsList:
                    authsList = list(authsList)
                    detailedInfo = attributeMaker(R)
                    if len(authsList) > 1:
                        for i, auth1 in enumerate(authsList):
                            if auth1 not in grph:
                                grph.add_node(auth1, attr_dict = detailedInfo)
                            elif count:
                                grph.node[auth1]['count'] += 1
                            for auth2 in authsList[i + 1:]:
                                if auth2 not in grph:
                                    grph.add_node(auth2, attr_dict = detailedInfo)
                                elif count:
                                    grph.node[auth2]['count'] += 1
                                if grph.has_edge(auth1, auth2) and weighted:
                                    grph.edge[auth1][auth2]['weight'] += 1
                                elif weighted:
                                    grph.add_edge(auth1, auth2, weight = 1)
                                else:
                                    grph.add_edge(auth1, auth2)
                    else:
                        auth1 = authsList[0]
                        if auth1 not in grph:
                            grph.add_node(auth1, attr_dict = detailedInfo)
                        elif count:
                            grph.node[auth1]['count'] += 1
            if PBar:
                PBar.finish("Done making a co-authorship network")
        return grph

    def coCiteNetwork(self, dropAnon = True, nodeType = "full", nodeInfo = True, fullInfo = False, weighted = True, dropNonJournals = False, count = True, keyWords = None, detailedCore = None, coreOnly = False, expandedCore = False):
        """Creates a co-citation network for the RecordCollection.

        # Parameters

        _nodeType_ : `optional [str]`

        > One of `"full"`, `"original"`, `"author"`, `"journal"` or `"year"`. Specifies the value of the nodes in the graph. The default `"full"` causes the citations to be compared holistically using the [`metaknowledge.Citation`](#Citation.Citation) builtin comparison operators. `"original"` uses the raw original strings of the citations. While `"author"`, `"journal"` and `"year"` each use the author, journal and year respectively.

        _dropAnon_ : `optional [bool]`

        > default `True`, if `True` citations labeled anonymous are removed from the network

        _nodeInfo_ : `optional [bool]`

        > default `True`, if `True` an extra piece of information is stored with each node. The extra inforamtion is detemined by _nodeType_.

        _fullInfo_ : `optional [bool]`

        > default `False`, if `True` the original citation string is added to the node as an extra value, the attribute is labeled as fullCite

        _weighted_ : `optional [bool]`

        > default `True`, wether the edges are weighted. If `True` the edges are weighted by the number of citations.

        _dropNonJournals_ : `optional [bool]`

        > default `False`, wether to drop citations of non-journals

        _count_ : `optional [bool]`

        > default `True`, causes the number of occurrences of a node to be counted

        _keyWords_ : `optional [str] or [list[str]]`

        > A string or list of strings that the citations are checked against, if they contain any of the strings they are removed from the network

        _detailedCore_ : `optional [bool or iterable[WOS tag Strings]]`

        > default `False`, if `True` all Citations from the core (those of records in the RecordCollection) and the _nodeType_ is `'full'` all nodes from the core will be given info strings composed of information from the Record objects themselves. This is Equivalent to passing the list: `['AF', 'PY', 'TI', 'SO', 'VL', 'BP']`.

        > If _detailedCore_ is an iterable (That evaluates to `True`) of WOS Tags (or long names) The values  of those tags will be used to make the info attribute. All

        > The resultant string is the values of each tag, with commas removed, seperated by `', '`, just like the info given by non-core Citations. Note that for tags like `'AF'` that return lists only the first entry in the list will be used. Also a second attribute is created for all nodes called inCore wich is a boolean describing if the node is in the core or not.

        > Note: _detailedCore_  is not identical to the _detailedInfo_ argument of [`Recordcollection.coAuthNetwork()`](#RecordCollection.coAuthNetwork)

        _coreOnly_ : `optional [bool]`

        > default `False`, if `True` only Citations from the RecordCollection will be included in the network

        _expandedCore_ : `optional [bool]`

        > default `False`, if `True` all citations in the ouput graph that are records in the collection will be duplicated for each author. If the nodes are `"full"`, `"original"` or `"author"` this will result in new noded being created for the other options the results are **not** defined or tested. Edges will be created between each of the nodes for each record expanded, attributes will be copied from exiting nodes.

        # Returns

        `Networkx Graph`

        > A networkx graph with hashes as ID and co-citation as edges
        """
        allowedTypes = ["full", "original", "author", "journal", "year"]
        if nodeType not in allowedTypes:
            raise RCValueError("{} is not an allowed nodeType.".format(nodeType))
        coreValues = []
        if bool(detailedCore):
            try:
                for tag in detailedCore:
                    coreValues.append(normalizeToTag(tag))
            except TypeError:
                coreValues = ['AF', 'PY', 'TI', 'SO', 'VL', 'BP']
        tmpgrph = nx.Graph()
        pcount = 0
        progArgs = (0, "Starting to make a co-citation network")
        if metaknowledge.VERBOSE_MODE:
            progKwargs = {'dummy' : False}
        else:
            progKwargs = {'dummy' : True}
        with _ProgressBar(*progArgs, **progKwargs) as PBar:
            if coreOnly or coreValues or expandedCore:
                coreCitesDict = {R.createCitation() : R for R in self}
                if coreOnly:
                    coreCites = coreCitesDict.keys()
                else:
                    coreCites = None
            else:
                coreCitesDict = None
                coreCites = None
            for R in self:
                if PBar:
                    pcount += 1
                    PBar.updateVal(pcount / len(self), "Analyzing: {}".format(R))
                Cites = R.get('citations')
                if Cites:
                    filteredCites = filterCites(Cites, nodeType, dropAnon, dropNonJournals, keyWords, coreCites)
                    addToNetwork(tmpgrph, filteredCites, count, weighted, nodeType, nodeInfo , fullInfo, coreCitesDict, coreValues, headNd = None)
            if expandedCore:
                if PBar:
                    PBar.updateVal(.98, "Expanding core Records")
                expandRecs(tmpgrph, self, nodeType, weighted)
            if PBar:
                PBar.finish("Done making a co-citation network of " + repr(self))
        return tmpgrph


    def citationNetwork(self, dropAnon = True, nodeType = "full", nodeInfo = True, fullInfo = False, weighted = True, dropNonJournals = False, count = True, directed = True, keyWords = None, detailedCore = None, coreOnly = False, expandedCore = False):

        """Creates a citation network for the RecordCollection.

        # Parameters

        _nodeType_ : `optional [str]`

        > One of `"full"`, `"original"`, `"author"`, `"journal"` or `"year"`. Specifies the value of the nodes in the graph. The default `"full"` causes the citations to be compared holistically using the [`metaknowledge.Citation`](#Citation.Citation) builtin comparison operators. `"original"` uses the raw original strings of the citations. While `"author"`, `"journal"` and `"year"` each use the author, journal and year respectively.

        _dropAnon_ : `optional [bool]`

        > default `True`, if `True` citations labeled anonymous are removed from the network

        _nodeInfo_ : `optional [bool]`

        > default `True`, wether an extra piece of information is stored with each node.

        _fullInfo_ : `optional [bool]`

        > default `False`, wether the original citation string is added to the node as an extra value, the attribute is labeled as fullCite

        _weighted_ : `optional [bool]`

        > default `True`, wether the edges are weighted. If `True` the edges are weighted by the number of citations.

        _dropNonJournals_ : `optional [bool]`

        > default `False`, wether to drop citations of non-journals

        _count_ : `optional [bool]`

        > default `True`, causes the number of occurrences of a node to be counted

        _keyWords_ : `optional [str] or [list[str]]`

        > A string or list of strings that the citations are checked against, if they contain any of the strings they are removed from the network

        _directed_ : `optional [bool]`

        > Determines if the output graph is directed, default `True`

        _detailedCore_ : `optional [bool or iterable[WOS tag Strings]]`

        > default `False`, if `True` all Citations from the core (those of records in the RecordCollection) and the _nodeType_ is `'full'` all nodes from the core will be given info strings composed of information from the Record objects themselves. This is Equivalent to passing the list: `['AF', 'PY', 'TI', 'SO', 'VL', 'BP']`.

        > If _detailedCore_ is an iterable (That evaluates to `True`) of WOS Tags (or long names) The values  of those tags will be used to make the info attribute. All

        > The resultant string is the values of each tag, with commas removed, seperated by `', '`, just like the info given by non-core Citations. Note that for tags like `'AF'` that return lists only the first entry in the list will be used. Also a second attribute is created for all nodes called inCore wich is a boolean describing if the node is in the core or not.

        > Note: _detailedCore_  is not identical to the _detailedInfo_ argument of [`Recordcollection.coAuthNetwork()`](#RecordCollection.coAuthNetwork)

        _coreOnly_ : `optional [bool]`

        > default `False`, if `True` only Citations from the RecordCollection will be included in the network

        _expandedCore_ : `optional [bool]`

        > default `False`, if `True` all citations in the ouput graph that are records in the collection will be duplicated for each author. If the nodes are `"full"`, `"original"` or `"author"` this will result in new noded being created for the other options the results are **not** defined or tested. Edges will be created between each of the nodes for each record expanded, attributes will be copied from exiting nodes.

        # Returns

        `Networkx DiGraph or Networkx Graph`

        > See _directed_ for explanation of returned type

        > A networkx digraph with hashes as ID and citations as edges
        """
        allowedTypes = ["full", "original", "author", "journal", "year"]
        if nodeType not in allowedTypes:
            raise RCValueError("{} is not an allowed nodeType.".format(nodeType))
        coreValues = []
        if bool(detailedCore):
            try:
                for tag in detailedCore:
                    coreValues.append(normalizeToTag(tag))
            except TypeError:
                coreValues = ['AF', 'PY', 'TI', 'SO', 'VL', 'BP']
        if directed:
            tmpgrph = nx.DiGraph()
        else:
            tmpgrph = nx.Graph()
        pcount = 0
        progArgs = (0, "Starting to make a citation network")
        if metaknowledge.VERBOSE_MODE:
            progKwargs = {'dummy' : False}
        else:
            progKwargs = {'dummy' : True}
        with _ProgressBar(*progArgs, **progKwargs) as PBar:
            if coreOnly or coreValues:
                coreCitesDict = {R.createCitation() : R for R in self}
                if coreOnly:
                    coreCites = coreCitesDict.keys()
                else:
                    coreCites = None
            else:
                coreCitesDict = None
                coreCites = None
            for R in self:
                if PBar:
                    pcount += 1
                    PBar.updateVal(pcount/ len(self), "Analyzing: " + str(R))
                reRef = R.createCitation()
                if len(filterCites([reRef], nodeType, dropAnon, dropNonJournals, keyWords, coreCites)) == 0:
                    continue
                rCites = R.get('citations')
                if rCites:
                    filteredCites = filterCites(rCites, nodeType, dropAnon, dropNonJournals, keyWords, coreCites)
                    addToNetwork(tmpgrph, filteredCites, count, weighted, nodeType, nodeInfo, fullInfo, coreCitesDict, coreValues, headNd = reRef)
            if expandedCore:
                if PBar:
                    PBar.updateVal(.98, "Expanding core Records")
                expandRecs(tmpgrph, self, nodeType, weighted)
            if PBar:
                PBar.finish("Done making a citation network of " + repr(self))
        return tmpgrph

    def _extractTagged(self, taglist):
        recordsWithTags = set()
        for R in self:
            for t in taglist:
                hasTags = True
                if t not in R.tags:
                    hasTags = False
                    break
            if hasTags:
                recordsWithTags.add(R)
        return RecordCollection(recordsWithTags, repr(self) + "_tags(" + ','.join(taglist) + ')', quietStart = True)

    def yearSplit(self, startYear, endYear, dropMissingYears = True):
        """Creates a RecordCollection of Records from the years between _startYear_ and _endYear_ inclusive.

        # Parameters

        _startYear_ : `int`

        > The smallest year to be included in the returned RecordCollection

        _endYear_ : `int`

        > The largest year to be included in the returned RecordCollection

        _dropMissingYears_ : `optional [bool]`

        > Default `True`, if `True` Records with missing years will be dropped. If `False` a `TypeError` exception will be raised

        # Returns

        `RecordCollection`

        > A RecordCollection of Records from _startYear_ to _endYear_
        """
        recordsInRange = set()
        for R in self:
            try:
                if R.get('year') >= startYear and R.get('year') <= endYear:
                    recordsInRange.add(R)
            except TypeError:
                if dropMissingYears:
                    pass
                else:
                    raise
        return RecordCollection(recordsInRange, name = "{}({}-{})".format(self.name, startYear, endYear), quietStart = True)

    def oneModeNetwork(self, mode, nodeCount = True, edgeWeight = True, stemmer = None, edgeAttribute = None, nodeAttribute = None):
        """Creates a network of the objects found by one WOS tag _mode_.

        A **oneModeNetwork**() looks are each Record in the RecordCollection and extracts its values for the tag given by _mode_, e.g. the `'AF'` tag. Then if multiple are returned an edge is created between them. So in the case of the author tag `'AF'` a co-authorship network is created.

        The number of times each object occurs is count if _nodeCount_ is `True` and the edges count the number of co-occurrences if _edgeWeight_ is `True`. Both are`True` by default.

        **Note** Do not use this for the construction of co-citation networks use [Recordcollection.coCiteNetwork()](#RecordCollection.coCiteNetwork) it is more accurate and has more options.

        # Parameters

        _mode_ : `str`

        > A two character WOS tag or one of the full names for a tag

        _nodeCount_ : `optional [bool]`

        > Default `True`, if `True` each node will have an attribute called "count" that contains an int giving the number of time the object occurred.

        _edgeWeight_ : `optional [bool]`

        > Default `True`, if `True` each edge will have an attribute called "weight" that contains an int giving the number of time the two objects co-occurrenced.

        _stemmer_ : `optional [func]`

        > Default `None`, If _stemmer_ is a callable object, basically a function or possibly a class, it will be called for the ID of every node in the graph, all IDs are strings. For example:

        > The function ` f = lambda x: x[0]` if given as the stemmer will cause all IDs to be the first character of their unstemmed IDs. e.g. the title `'Goos-Hanchen and Imbert-Fedorov shifts for leaky guided modes'` will create the node `'G'`.

        # Returns

        `networkx Graph`

        > A networkx Graph with the objects of the tag _mode_ as nodes and their co-occurrences as edges
        """
        if not isinstance(mode, str):
            raise TypeError("{} is not a string, it cannot be a tag".format(mode))
        stemCheck = False
        if stemmer is not None:
            if isinstance(stemmer, collections.abc.Callable):
                stemCheck = True
            else:
                raise TypeError("stemmer must be callable, e.g. a function or class with a __call__ method.")
        count = 0
        progArgs = (0, "Starting to make a one mode network with " + mode)
        if metaknowledge.VERBOSE_MODE:
            progKwargs = {'dummy' : False}
        else:
            progKwargs = {'dummy' : True}
        with _ProgressBar(*progArgs, **progKwargs) as PBar:
            if edgeAttribute is not None:
                grph = nx.MultiGraph()
            else:
                grph = nx.Graph()
            for R in self:
                if PBar:
                    count += 1
                    PBar.updateVal(count / len(self), "Analyzing: " + str(R))
                if edgeAttribute:
                    edgeVals = [str(v) for v in R.get(edgeAttribute, [])]
                if nodeAttribute:
                    nodeVals = [str(v) for v in R.get(nodeAttribute, [])]
                if isinstance(mode, list):
                    contents = []
                    for attr in mode:
                        tmpContents = R.get(attr, [])
                        if isinstance(tmpContents, list):
                            contents += tmpContents
                        else:
                            contents.append(tmpContents)
                else:
                    contents = R.get(mode)
                if contents is not None:
                    if not isinstance(contents, str) and isinstance(contents, collections.abc.Iterable):
                        if stemCheck:
                            tmplst = [stemmer(str(n)) for n in contents]
                        else:
                            tmplst = [str(n) for n in contents]
                        if len(tmplst) > 1:
                            for i, node1 in enumerate(tmplst):
                                for node2 in tmplst[i + 1:]:
                                    if edgeAttribute:
                                        for edgeVal in edgeVals:
                                            if grph.has_edge(node1, node2, key = edgeVal):
                                                if edgeWeight:
                                                    for i, a in grph[node1][node2].items():
                                                        if a['key'] == edgeVal:
                                                            grph[node1][node2][i]['weight'] += 1
                                                            break
                                            else:
                                                if edgeWeight:
                                                    attrDict = {'key' : edgeVal, 'weight' : 1}
                                                else:
                                                    attrDict = {'key' : edgeVal}
                                                grph.add_edge(node1, node2, attr_dict = attrDict)
                                    elif edgeWeight:
                                        try:
                                            grph.edge[node1][node2]['weight'] += 1
                                        except KeyError:
                                            grph.add_edge(node1, node2, weight = 1)
                                    else:
                                        if not grph.has_edge(node1, node2):
                                            grph.add_edge(node1, node2)
                                if not grph.has_node(node1):
                                    grph.add_node(node1)
                                if nodeCount:
                                    try:
                                        grph.node[node1]['count'] += 1
                                    except KeyError:
                                        grph.node[node1]['count'] = 1
                                if nodeAttribute:
                                    try:
                                        currentAttrib = grph.node[node1][nodeAttribute]
                                    except KeyError:
                                        grph.node[node1][nodeAttribute] = nodeVals
                                    else:
                                        for nodeValue in (n for n in nodeVals if n not in currentAttrib):
                                                grph.node[node1][nodeAttribute].append(nodeValue)
                        elif len(tmplst) == 1:
                            if nodeCount:
                                try:
                                    grph.node[tmplst[0]]['count'] += 1
                                except KeyError:
                                    grph.add_node(tmplst[0], count = 1)
                            else:
                                if not grph.has_node(tmplst[0]):
                                    grph.add_node(tmplst[0])
                            if nodeAttribute:
                                try:
                                    currentAttrib = grph.node[tmplst[0]][nodeAttribute]
                                except KeyError:
                                    grph.node[tmplst[0]][nodeAttribute] = nodeVals
                                else:
                                    for nodeValue in (n for n in nodeVals if n not in currentAttrib):
                                            grph.node[tmplst[0]][nodeAttribute].append(nodeValue)
                        else:
                            pass
                    else:
                        if stemCheck:
                            nodeVal = stemmer(str(contents))
                        else:
                            nodeVal = str(contents)
                        if nodeCount:
                            try:
                                grph.node[nodeVal]['count'] += 1
                            except KeyError:
                                grph.add_node(nodeVal, count = 1)
                        else:
                            if not grph.has_node(nodeVal):
                                grph.add_node(nodeVal)
                        if nodeAttribute:
                            try:
                                currentAttrib = grph.node[nodeVal][nodeAttribute]
                            except KeyError:
                                grph.node[nodeVal][nodeAttribute] = nodeVals
                            else:
                                for nodeValue in (n for n in nodeVals if n not in currentAttrib):
                                        grph.node[nodeVal][nodeAttribute].append(nodeValue)
            if PBar:
                PBar.finish("Done making a one mode network with {}".format(mode))
        return grph

    def twoModeNetwork(self, tag1, tag2, directed = False, recordType = True, nodeCount = True, edgeWeight = True, stemmerTag1 = None, stemmerTag2 = None):
        """Creates a network of the objects found by two WOS tags _tag1_ and _tag2_, each node marked by which tag spawned it making the resultant graph bipartite.

        A **twoModeNetwork()** looks at each Record in the `RecordCollection` and extracts its values for the tags given by _tag1_ and _tag2_, e.g. the `'WC'` and `'LA'` tags. Then for each object returned by each tag and edge is created between it and every other object of the other tag. So the WOS defined subject tag `'WC'` and language tag `'LA'`, will give a two-mode network showing the connections between subjects and languages. Each node will have an attribute call `'type'` that gives the tag that created it or both if both created it, e.g. the node `'English'` would have the type attribute be `'LA'`.

        The number of times each object occurs is count if _nodeCount_ is `True` and the edges count the number of co-occurrences if _edgeWeight_ is `True`. Both are`True` by default.

        The _directed_ parameter if `True` will cause the network to be directed with the first tag as the source and the second as the destination.

        # Parameters

        _tag1_ : `str`

        > A two character WOS tag or one of the full names for a tag, the source of edges on the graph

        _tag1_ : `str`

        > A two character WOS tag or one of the full names for a tag, the target of edges on the graph

        _directed_ : `optional [bool]`

        > Default `False`, if `True` the returned network is directed

        _nodeCount_ : `optional [bool]`

        > Default `True`, if `True` each node will have an attribute called "count" that contains an int giving the number of time the object occurred.

        _edgeWeight_ : `optional [bool]`

        > Default `True`, if `True` each edge will have an attribute called "weight" that contains an int giving the number of time the two objects co-occurrenced.

        _stemmerTag1_ : `optional [func]`

        > Default `None`, If _stemmerTag1_ is a callable object, basically a function or possibly a class, it will be called for the ID of every node given by _tag1_ in the graph, all IDs are strings.

        > For example: the function `f = lambda x: x[0]` if given as the stemmer will cause all IDs to be the first character of their unstemmed IDs. e.g. the title `'Goos-Hanchen and Imbert-Fedorov shifts for leaky guided modes'` will create the node `'G'`.

        _stemmerTag2_ : `optional [func]`

        > Default `None`, see _stemmerTag1_ as it is the same but for _tag2_

        # Returns

        `networkx Graph or networkx DiGraph`

        > A networkx Graph with the objects of the tags _tag1_ and _tag2_ as nodes and their co-occurrences as edges.
        """
        if not isinstance(tag1, str):
            raise TypeError("{} is not a string it cannot be a tag.".format(tag1))
        if not isinstance(tag2, str):
            raise TypeError("{} is not a string it cannot be a tag.".format(tag2))
        if stemmerTag1 is not None:
            if isinstance(stemmerTag1, collections.abc.Callable):
                stemCheck = True
            else:
                raise TypeError("stemmerTag1 must be callable, e.g. a function or class with a __call__ method.")
        else:
            stemmerTag1 = lambda x: x
        if stemmerTag2 is not None:
            if isinstance(stemmerTag2, collections.abc.Callable):
                stemCheck = True
            else:
                raise TypeError("stemmerTag2 must be callable, e.g. a function or class with a __call__ method.")
        else:
            stemmerTag2 = lambda x: x
        count = 0
        progArgs = (0, "Starting to make a two mode network of " + tag1 + " and " + tag2)
        if metaknowledge.VERBOSE_MODE:
            progKwargs = {'dummy' : False}
        else:
            progKwargs = {'dummy' : True}
        with _ProgressBar(*progArgs, **progKwargs) as PBar:
            if directed:
                grph = nx.DiGraph()
            else:
                grph = nx.Graph()
            for R in self:
                if PBar:
                    count += 1
                    PBar.updateVal(count / len(self), "Analyzing: " + str(R))
                contents1 = R.get(tag1)
                contents2 = R.get(tag2)
                if isinstance(contents1, list):
                    contents1 = [stemmerTag1(str(v)) for v in contents1]
                elif contents1 == None:
                    contents1 = []
                else:
                    contents1 = [stemmerTag1(str(contents1))]
                if isinstance(contents2, list):
                    contents2 = [stemmerTag2(str(v)) for v in contents2]
                elif contents2 == None:
                    contents2 = []
                else:
                    contents2 = [stemmerTag2(str(contents2))]
                for node1 in contents1:
                    for node2 in contents2:
                        if edgeWeight:
                            try:
                                grph.edge[node1][node2]['weight'] += 1
                            except KeyError:
                                grph.add_edge(node1, node2, weight = 1)
                        else:
                            if not grph.has_edge(node1, node2):
                                grph.add_edge(node1, node2)
                    if nodeCount:
                        try:
                            grph.node[node1]['count'] += 1
                        except KeyError:
                            try:
                                grph.node[node1]['count'] = 1
                                if recordType:
                                    grph.node[node1]['type'] = tag1
                            except KeyError:
                                if recordType:
                                    grph.add_node(node1, type = tag1)
                                else:
                                    grph.add_node(node1)
                    else:
                        if not grph.has_node(node1):
                            if recordType:
                                grph.add_node(node1, type = tag1)
                            else:
                                grph.add_node(node1)
                        elif recordType:
                            if 'type' not in grph.node[node1]:
                                grph.node[node1]['type'] = tag1

                for node2 in contents2:
                    if nodeCount:
                        try:
                            grph.node[node2]['count'] += 1
                        except KeyError:
                            try:
                                grph.node[node2]['count'] = 1
                                if recordType:
                                    grph.node[node2]['type'] = tag2
                            except KeyError:
                                grph.add_node(node2, count = 1)
                                if recordType:
                                    grph.node[node2]['type'] = tag2
                    else:
                        if not grph.has_node(node2):
                            if recordType:
                                grph.add_node(node2, type = tag2)
                            else:
                                grph.add_node(node2)
                        elif recordType:
                            if 'type' not in grph.node[node2]:
                                grph.node[node2]['type'] = tag2
            if PBar:
                PBar.finish("Done making a two mode network of " + tag1 + " and " + tag2)
        return grph

    def nModeNetwork(self, tags, recordType = True, nodeCount = True, edgeWeight = True, stemmer = None):
        """Creates a network of the objects found by all WOS tags in _tags_, each node is marked by which tag spawned it making the resultant graph n-partite.

        A **nModeNetwork()** looks are each Record in the RecordCollection and extracts its values for the tags given by _tags_. Then for all objects returned an edge is created between them, regardless of their type. Each node will have an attribute call `'type'` that gives the tag that created it or both if both created it, e.g. if `'LA'` were in _tags_ node `'English'` would have the type attribute be `'LA'`.

        For example if _tags_ was set to `['CR', 'UT', 'LA']`, a three mode network would be created, composed of a co-citation network from the `'CR'` tag. Then each citation would also have edges to all the languages of Records that cited it and to the WOS number of the those Records.

        The number of times each object occurs is count if _nodeCount_ is `True` and the edges count the number of co-occurrences if _edgeWeight_ is `True`. Both are`True` by default.

        # Parameters

        _mode_ : `str`

        > A two character WOS tag or one of the full names for a tag

        _nodeCount_ : `optional [bool]`

        > Default `True`, if `True` each node will have an attribute called `'count'` that contains an int giving the number of time the object occurred.

        _edgeWeight_ : `optional [bool]`

        > Default `True`, if `True` each edge will have an attribute called `'weight'` that contains an int giving the number of time the two objects co-occurrenced.

        _stemmer_ : `optional [func]`

        > Default `None`, If _stemmer_ is a callable object, basically a function or possibly a class, it will be called for the ID of every node in the graph, note that all IDs are strings.

        > For example: the function `f = lambda x: x[0]` if given as the stemmer will cause all IDs to be the first character of their unstemmed IDs. e.g. the title `'Goos-Hanchen and Imbert-Fedorov shifts for leaky guided modes'` will create the node `'G'`.

        # Returns

        `networkx Graph`

        > A networkx Graph with the objects of the tags _tags_ as nodes and their co-occurrences as edges
        """
        for t in (i for i in tags if not isinstance(i, str)):
            raise TypeError("{} is not a string it cannot be a tag.".format(t))
        stemCheck = False
        if stemmer is not None:
            if isinstance(stemmer, collections.abc.Callable):
                stemCheck = True
            else:
                raise TypeError("stemmer must be Callable, e.g. a function or class with a __call__ method.")
        count = 0
        progArgs = (0, "Starting to make a " + str(len(tags)) + "-mode network of: " + ', '.join(tags))
        if metaknowledge.VERBOSE_MODE:
            progKwargs = {'dummy' : False}
        else:
            progKwargs = {'dummy' : True}
        with _ProgressBar(*progArgs, **progKwargs) as PBar:
            grph = nx.Graph()
            for R in self:
                if PBar:
                    count += 1
                    PBar.updateVal(count / len(self), "Analyzing: " + str(R))
                contents = []
                for t in tags:
                    tmpVal = R.get(t)
                    if stemCheck:
                        if tmpVal:
                            if isinstance(tmpVal, list):
                                contents.append((t, [stemmer(str(v)) for v in tmpVal]))
                            else:
                                contents.append((t, [stemmer(str(tmpVal))]))
                    else:
                        if tmpVal:
                            if isinstance(tmpVal, list):
                                contents.append((t, [str(v) for v in tmpVal]))
                            else:
                                contents.append((t, [str(tmpVal)]))
                for i, vlst1 in enumerate(contents):
                    for node1 in vlst1[1]:
                        for vlst2 in contents[i + 1:]:
                            for node2 in vlst2[1]:
                                if edgeWeight:
                                    try:
                                        grph.edge[node1][node2]['weight'] += 1
                                    except KeyError:
                                        grph.add_edge(node1, node2, weight = 1)
                                else:
                                    if not grph.has_edge(node1, node2):
                                        grph.add_edge(node1, node2)
                        if nodeCount:
                            try:
                                grph.node[node1]['count'] += 1
                            except KeyError:
                                try:
                                    grph.node[node1]['count'] = 1
                                    if recordType:
                                        grph.node[node1]['type'] = vlst1[0]
                                except KeyError:
                                    if recordType:
                                        grph.add_node(node1, type = vlst1[0])
                                    else:
                                        grph.add_node(node1)
                        else:
                            if not grph.has_node(node1):
                                if recordType:
                                    grph.add_node(node1, type = vlst1[0])
                                else:
                                    grph.add_node(node1)
                            elif recordType:
                                try:
                                    grph.node[node1]['type'] += vlst1[0]
                                except KeyError:
                                    grph.node[node1]['type'] = vlst1[0]
            if PBar:
                PBar.finish("Done making a " + str(len(tags)) + "-mode network of: " +  ', '.join(tags))
        return grph

    def localCiteStats(self, pandasFriendly = False, keyType = "citation"):
        """Returns a dict with all the citations in the CR field as keys and the number of times they occur as the values

        # Parameters

        _pandasFriendly_ : `optional [bool]`

        > default `False`, makes the output be a dict with two keys one `'Citations'` is the citations the other is their occurrence counts as `'Counts'`.

        _keyType_ : `optional [str]`

        > default `'citation'`, the type of key to use for the dictionary, the valid strings are `'citation'`, `'journal'`, `'year'` or `'author'`. IF changed from `'citation'` all citations matching the requested option will be contracted and their counts added together.

        # Returns

        `dict[str, int or Citation : int]`

        > A dictionary with keys as given by _keyType_ and integers giving their rates of occurrence in the collection
        """
        count = 0
        recCount = len(self)
        progArgs = (0, "Starting to get the local stats on {}s.".format(keyType))
        if metaknowledge.VERBOSE_MODE:
            progKwargs = {'dummy' : False}
        else:
            progKwargs = {'dummy' : True}
        with _ProgressBar(*progArgs, **progKwargs) as PBar:
            keyTypesLst = ["citation", "journal", "year", "author"]
            citesDict = {}
            if keyType not in keyTypesLst:
                raise TypeError("{} is not a valid key type, only '{}' or '{}' are.".format(keyType, "', '".join(keyTypesLst[:-1]), keyTypesLst[-1]))
            for R in self:
                rCites = R.get('citations')
                if PBar:
                    count += 1
                    PBar.updateVal(count / recCount, "Analysing: {}".format(R.UT))
                if rCites:
                    for c in rCites:
                        if keyType == keyTypesLst[0]:
                            cVal = c
                        else:
                            cVal = getattr(c, keyType)
                            if cVal is None:
                                continue
                        if cVal in citesDict:
                            citesDict[cVal] += 1
                        else:
                            citesDict[cVal] = 1
            if PBar:
                PBar.finish("Done, {} {} fields analysed".format(len(citesDict), keyType))
        if pandasFriendly:
            citeLst = []
            countLst = []
            for cite, occ in citesDict.items():
                citeLst.append(cite)
                countLst.append(occ)
            return {"Citations" : citeLst, "Counts" : countLst}
        else:
            return citesDict

    def localCitesOf(self, rec):
        """Takes in a Record, WOS string, citation string or Citation and returns a RecordCollection of all records that cite it.

        # Parameters

        _rec_ : `Record, str or Citation`

        > The object that is being cited

        # Returns

        `RecordCollection`

        > A `RecordCollection` containing only those `Records` that cite _rec_
        """
        localCites = []
        if isinstance(rec, Record):
            recCite = rec.createCitation()
        if isinstance(rec, str):
            try:
                recCite = self.getID(rec)
            except ValueError:
                try:
                    recCite = Citation(rec)
                except AttributeError:
                    raise ValueError("{} is not a valid WOS string or a valid citation string".format(recCite))
            else:
                if recCite is None:
                    return RecordCollection(inCollection = localCites, name = "Records_citing_{}".format(rec), quietStart = True)
                else:
                    recCite = recCite.createCitation()
        elif isinstance(rec, Citation):
            recCite = rec
        else:
            raise ValueError("{} is not a valid input, rec must be a Record, string or Citation object.".format(rec))
        for R in self:
            rCites = R.get('citations')
            if rCites:
                for cite in rCites:
                    if recCite == cite:
                        localCites.append(R)
                        break
        return RecordCollection(inCollection = localCites, name = "Records_citing_'{}'".format(rec), quietStart = True)

    def citeFilter(self, keyString = '', field = 'all', reverse = False, caseSensitive = False):
        """Filters `Records` by some string, _keyString_, in their citations and returns all `Records` with at least one citation possessing _keyString_ in the field given by _field_.

        # Parameters

        _keyString_ : `optional [str]`

        > Default `''`, gives the string to be searched for, if it is is blank then all citations with the specified field will be matched

        _field_ : `optional [str]`

        > Default `'all'`, gives the component of the citation to be looked at, it can be one of a few strings. The default is `'all'` which will cause the entire original `Citation` to be searched. It can be used to search across fields, e.g. `'1970, V2'` is a valid keystring
        The other options are:

        + `'author'`, searches the author field
        + `'year'`, searches the year field
        + `'journal'`, searches the journal field
        + `'V'`, searches the volume field
        + `'P'`, searches the page field
        + `'misc'`, searches all the remaining uncategorized information
        + `'anonymous'`, searches for anonymous `Citations`, _keyString_ is not ignored
        + `'bad'`, searches for bad citations, keyString is not used

        _reverse_ : `optional [bool]`

        > Default `False`, being set to `True` causes all `Records` not matching the query to be returned

        _caseSensitive_ : `optional [bool]`

        > Default `False`, if `True` causes the search across the original to be case sensitive, **only** the `'all'` option can be case sensitive
        """
        retRecs = []
        keyString = str(keyString)
        for R in self:
            try:
                if field == 'all':
                    for cite in R.get('citations'):
                        if caseSensitive:
                            if keyString in cite.original:
                                retRecs.append(R)
                                break
                        else:
                            if keyString.upper() in cite.original.upper():
                                retRecs.append(R)
                                break
                elif field == 'author':
                    for cite in R.get('citations'):
                        try:
                            if keyString.upper() in cite.author.upper():
                                retRecs.append(R)
                                break
                        except AttributeError:
                            pass
                elif field == 'journal':
                    for cite in R.get('citations'):
                        try:
                            if keyString.upper() in cite.journal:
                                retRecs.append(R)
                                break
                        except AttributeError:
                            pass
                elif field == 'year':
                    for cite in R.get('citations'):
                        try:
                            if int(keyString) == cite.year:
                                retRecs.append(R)
                                break
                        except AttributeError:
                            pass
                elif field == 'V':
                    for cite in R.get('citations'):
                        try:
                            if keyString.upper() in cite.V:
                                retRecs.append(R)
                                break
                        except AttributeError:
                            pass
                elif field == 'P':
                    for cite in R.get('citations'):
                        try:
                            if keyString.upper() in cite.P:
                                retRecs.append(R)
                                break
                        except AttributeError:
                            pass
                elif field == 'misc':
                    for cite in R.get('citations'):
                        try:
                            if keyString.upper() in cite.misc:
                                retRecs.append(R)
                                break
                        except AttributeError:
                            pass
                elif field == 'anonymous':
                    for cite in R.get('citations'):
                        if cite.isAnonymous():
                            retRecs.append(R)
                            break
                elif field == 'bad':
                    for cite in R.get('citations'):
                        if cite.bad:
                            retRecs.append(R)
                            break
            except TypeError:
                pass
        if reverse:
            excluded = []
            for R in self:
                if R not in retRecs:
                    excluded.append(R)
            return RecordCollection(inCollection = excluded, name = self.name, quietStart = True)
        else:
            return RecordCollection(inCollection = retRecs, name = self.name, quietStart = True)

def getCoCiteIDs(clst):
    """
    Creates a dict of the ID-extra information pairs for a CR tag.
    """
    idDict = {}
    for c in clst:
        cId = c.ID()
        if cId not in idDict:
            idDict[cId] = c.Extra()
    return idDict

def updateWeightedEdges(grph, ebunch):
    for e in ebunch:
        try:
            grph.edge[e[0]][e[1]]['weight'] += e[2]
        except KeyError:
            grph.add_edge(e[0], e[1], weight = e[2])

def edgeBunchGenerator(base, nodes, weighted = False, reverse = False):
    """
    A helper function for generating a bunch of edges from 1 node base to a list of nodes nodes.
    """
    if weighted and reverse:
        for n in nodes:
            yield (n, base, 1)
    elif weighted:
        for n in nodes:
            yield (base, n, 1)
    elif reverse:
        for n in nodes:
            yield (n, base)
    else:
        for n in nodes:
            yield (base, n)

def edgeNodeReplacerGenerator(base, nodes, loc):
    """
    A helper function for replacing an element of nodes at loc with base
    """
    for n in nodes:
        tmpN = list(n)
        tmpN[loc] = base
        yield tmpN


def addToNetwork(grph, nds, count, weighted, nodeType, nodeInfo, fullInfo, coreCitesDict, coreValues, headNd = None):
    """Addeds the citations _nds_ to _grph_, according to the rules give by _nodeType_, _fullInfo_, etc.

    _headNd_ is the citation of the Record
    """
    if headNd is not None:
        hID = makeID(headNd, nodeType)
        if hID not in grph:
            grph.add_node(*makeNodeTuple(headNd, hID, nodeInfo, fullInfo, nodeType, count, coreCitesDict, coreValues))
    else:
        hID = None
    idList = []
    for n in nds:
        nID = makeID(n, nodeType)
        if nID not in grph:
            grph.add_node(*makeNodeTuple(n, nID, nodeInfo, fullInfo, nodeType, count, coreCitesDict, coreValues))
        elif count:
            grph.node[nID]['count'] += 1
        idList.append(nID)
    addedEdges = []
    if hID:
        for nID in idList:
            if weighted:
                try:
                    grph[hID][nID]['weight'] += 1
                except KeyError:
                    grph.add_edge(hID, nID, weight = 1)
            elif nID not in grph[hID]:
                addedEdges.append((hID, nID))
    elif len(idList) > 1:
        for i, outerID in enumerate(idList):
            for innerID in idList[i + 1:]:
                if weighted:
                    try:
                        grph[outerID][innerID]['weight'] += 1
                    except KeyError:
                        grph.add_edge(outerID, innerID, weight = 1)
                elif innerID not in grph[outerID]:
                    addedEdges.append((outerID, innerID))
    grph.add_edges_from(addedEdges)

def makeID(citation, nodeType):
    """Makes the id, of the correct type for the network"""
    if nodeType != "full":
        return getattr(citation, nodeType)
    else:
        return citation.ID()

def makeNodeTuple(citation, idVal, nodeInfo, fullInfo, nodeType, count, coreCitesDict, coreValues):
    """Makes a tuple of idVal and a dict of the selected attributes"""
    d = {}
    if nodeInfo:
        if nodeType == 'full':
            if coreValues:
                if citation in coreCitesDict:
                    R = coreCitesDict[citation]
                    infoVals = []
                    for tag in coreValues:
                        tagVal = R.get(tag)
                        if isinstance(tagVal, str):
                            infoVals.append(tagVal.replace(',',''))
                        elif isinstance(tagVal, list):
                            infoVals.append(tagVal[0].replace(',',''))
                        else:
                            pass
                    d['info'] = ', '.join(infoVals)
                    d['inCore'] = True
                else:
                    d['info'] = citation.allButDOI()
                    d['inCore'] = False
            else:
                d['info'] = citation.allButDOI()
        elif nodeType == 'journal':
            if citation.isJournal():
                d['info'] = str(citation.FullJournalName())
            else:
                d['info'] = "None"
        elif nodeType == 'original':
            d['info'] = str(citation)
        else:
            d['info'] = idVal
    if fullInfo:
        d['fullCite'] = str(citation)
    if count:
        d['count'] = 1
    return (idVal, d)

def filterCites(cites, nodeType, dropAnon, dropNonJournals, keyWords, coreCites):
    filteredCites = []
    for c in cites:
        if nodeType != "full" and not getattr(c, nodeType):
            pass
        elif dropNonJournals and not c.isJournal():
            pass
        elif dropAnon and c.isAnonymous():
            pass
        elif coreCites and c not in coreCites:
            pass
        elif keyWords:
            found = False
            citeString = str(c).upper()
            if isinstance(keyWords, str):
                if keyWords.upper() in citeString:
                    found = True
            else:
                for k in keyWords:
                    if k.upper() in citeString:
                        found = True
                        break
            if not found:
                filteredCites.append(c)
        else:
            filteredCites.append(c)
    return filteredCites

def expandRecs(G, RecCollect, nodeType, weighted):
    """Expand all the citations from _RecCollect_"""
    for Rec in RecCollect:
        fullCiteList = [makeID(c, nodeType) for c in Rec.createCitation(multiCite = True)]
        if len(fullCiteList) > 1:
            for i, citeID1 in enumerate(fullCiteList):
                if citeID1 in G:
                    for citeID2 in fullCiteList[i + 1:]:
                        if citeID2 not in G:
                            G.add_node(citeID2, attr_dict = G.node[citeID1])
                            if weighted:
                                G.add_edge(citeID1, citeID2, weight = 1)
                            else:
                                G.add_edge(citeID1, citeID2)
                        elif weighted:
                            try:
                                G.edge[citeID1][citeID2]['weight'] += 1
                            except KeyError:
                                G.add_edge(citeID1, citeID2, weight = 1)
                        for e1, e2, data in G.edges_iter(citeID1, data = True):
                            G.add_edge(citeID2, e2, attr_dict = data)


def loadCache(cacheFile, flist, rcName, fileExtensions, PBar):
    if PBar:
        PBar.updateVal(0, "Loading cached RecordCollection")
    with open(cacheFile, 'rb') as f:
        try:
            dat, RC = pickle.load(f)
        except pickle.PickleError as e:
            raise cacheError("pickle Error: {}".format(e))
    if dat["metaknowledge Version"] != __version__:
        raise cacheError("mk version mismatch")
    if dat["RecordCollection Name"] != rcName:
        raise cacheError("Name mismatch")
    if dat["File Extension"] != fileExtensions:
        raise cacheError("Extension mismatch")
    if len(flist) != len(dat["File dict"]):
        raise cacheError("File number mismatch")
    while len(flist) > 0:
        workingFile = flist.pop()
        try:
            if os.stat(workingFile).st_mtime != dat["File dict"][workingFile]:
                raise cacheError("File modification mismatch")
        except KeyError:
            raise cacheError("File modification mismatch")
    return RC

def writeCache(RC, cacheFile, flist, rcName, fileExtensions, PBar):
    if PBar:
        PBar.updateVal(1, "Writing RecordCollection cache to {}".format(cacheFile))
    dat = {
        "metaknowledge Version" : __version__,
        "File dict" : {},
        "RecordCollection Name" : rcName,
        "File Extension" : fileExtensions,
    }
    for fileName in flist:
        dat["File dict"][fileName] =  os.stat(fileName).st_mtime
    with open(cacheFile, 'wb') as f:
        pickle.dump((dat, RC), f)
