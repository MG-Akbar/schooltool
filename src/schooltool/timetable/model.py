#
# SchoolTool - common information systems platform for school administration
# Copyright (c) 2003 Shuttleworth Foundation
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#
"""
Timetable model implementations.

A timetable model describes the mapping between timetable days and calendar
days, and also the mapping between period IDs and time of the day.  Currently
SchoolTool has two kinds of timetable models:

  - Sequential days model may jump over calendar days if they are not school
    days.  For example, if July 3 was timetable day 3, and July 4 is a holiday,
    then July 5 will be timetable day 4.

  - Weekly model maps week days directly to timetable days, that is, Monday is
    always timetable day 1, and sunday is always timetable day 7.

It is possible to define additional models.  See ITimetableModel.

$Id$
"""
import socket
import itertools
import datetime

from persistent import Persistent
from persistent.dict import PersistentDict
from zope.interface import implements, classProvides
from zope.app.traversing.api import getPath

from schoolbell.app.cal import CalendarEvent
from schoolbell.calendar.simple import ImmutableCalendar

from schooltool.timetable.interfaces import ITimetableModel
from schooltool.timetable.interfaces import ITimetableModelFactory
from schooltool.timetable.interfaces import ITimetableCalendarEvent

__metaclass__ = type


class BaseTimetableModel(Persistent):
    """An abstract base class for timetable models.

    The models are persistent, but all the data structures inside,
    including the day templates, are not.  Timetable models are
    considered to be volatile.  Making the timetable models persistent
    is an optimisation.  Everything would work without that as well,
    but a separate pickle of a model would be included in each
    timetable.

    Subclasses must define these methods:

       def schooldayStrategy(self, date, day_iterator):
           '''Return a day_id for a certain date.

           Will be called sequentially for all school days.

           May return None if the schoolday model thinks that there should
           be no classes on this date.
           '''

       def _dayGenerator(self):
           '''Return an iterator to be passed to schooldayStrategy'''
    """
    implements(ITimetableModel)

    timetableDayIds = ()
    dayTemplates = {}       # overriden in the __init__s of descendants


    def __init__(self):
        self.exceptionDays = PersistentDict()
        self.exceptionDayIds = PersistentDict()

    def _validateDayTemplates(self):
        if None not in self.dayTemplates:
            for weekday in range(7):
                if weekday not in self.dayTemplates:
                    raise AssertionError("No day template for day %d,"
                                         " and no fallback either" % weekday)

    def createCalendar(self, term, timetable):
        uid_suffix = '%s@%s' % (getPath(timetable), socket.getfqdn())
        events = []
        day_id_gen = self._dayGenerator()

        for date in term:
            day_id, periods = self._periodsInDay(term, timetable,
                                                 date, day_id_gen)
            for period in periods:
                dt = datetime.datetime.combine(date, period.tstart)
                for activity in timetable[day_id][period.title]:
                    key = (date, period.title, activity)
                    # IDs for functionally derived calendars should be
                    # functionally derived, and not random
                    uid = '%d-%s' % (hash((activity.title, dt,
                                           period.duration)), uid_suffix)
                    event = TimetableCalendarEvent(
                                dt, period.duration, activity.title,
                                unique_id=uid,
                                period_id=period.title, activity=activity)
                    events.append(event)
        return ImmutableCalendar(events)

    def getDayId(self, term, day, day_id_gen=None):
        """See ITimetableModel.originalPeriodsInDay

        `day_id_gen` is an optimization for a case when all day ids
        are gotten in sequence, e.g. when generating a timetable
        calendar.
        """

        if day_id_gen is None:
            # Scroll to the required day
            day_id_gen = self._dayGenerator()
            if day_id_gen is not None:
                for date in term:
                    if date == day:
                        break
                    if term.isSchoolday(date):
                        self.schooldayStrategy(date, day_id_gen)

        if not term.isSchoolday(day):
            return None
        return self.schooldayStrategy(day, day_id_gen)

    def _periodsInDay(self, term, timetable, day,
                      day_id_gen=None, original=False):
        """Return a timetable day_id and a list of periods for a given day.

        if day_id_gen is not provided, a new generator is created and
        scrolled to the date requested.  If day_id_gen is provided, it
        is called once to gain a day_id.

        `original` is boolean flag that makes this method disregard
        exceptionDays.
        """

        day_id = self.getDayId(term, day, day_id_gen)
        if day_id is None:
            return None, []

        # Now choose the periods that are in this day
        result = []
        if original:
            day_template = self._getUsualTemplateForDay(day)
        else:
            day_template = self._getTemplateForDay(day)
        for period in day_template:
            dt = datetime.datetime.combine(day, period.tstart)
            if period.title in timetable[day_id].keys():
                result.append(period)

        result.sort(lambda x, y: cmp(x.tstart, y.tstart))
        return day_id, result

    def periodsInDay(self, term, timetable, day):
        """See ITimetableModel.periodsInDay"""
        return self._periodsInDay(term, timetable, day)[1]

    def originalPeriodsInDay(self, term, timetable, day):
        """See ITimetableModel.originalPeriodsInDay"""
        return self._periodsInDay(term, timetable, day, original=True)[1]

    def _getUsualTemplateForDay(self, date):
        """Returns the schoolday template for a certain date
        disregarding special days.
        """
        default = self.dayTemplates[None]
        return self.dayTemplates.get(date.weekday(), default)

    def _getTemplateForDay(self, date):
        """Returns the schoolday template for a certain date"""
        usual = self._getUsualTemplateForDay(date)
        return self.exceptionDays.get(date, usual)

    def schooldayStrategy(self, date, generator):
        raise NotImplementedError

    def _dayGenerator(self):
        raise NotImplementedError

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return (self.timetableDayIds == other.timetableDayIds and
                    self.dayTemplates == other.dayTemplates and
                    self.exceptionDays == other.exceptionDays and
                    self.exceptionDayIds == other.exceptionDayIds)
        else:
            return False

    def __ne__(self, other):
        return not self == other


class SequentialDaysTimetableModel(BaseTimetableModel):
    """A timetable model in which the school days go in sequence with
    shifts over non-schooldays:

    Mon     Day 1
    Tue     Day 2
    Wed     ----- National holiday!
    Thu     Day 3
    Fri     Day 4
    Sat     ----- Weekend
    Sun     -----
    Mon     Day 1
    Tue     Day 2
    Wed     Day 3
    Thu     Day 4
    Fri     Day 1
    Sat     ----- Weekend
    Sun     -----
    Mon     Day 2
    """

    factory_id = "SequentialDaysTimetableModel"

    classProvides(ITimetableModelFactory)

    def __init__(self, day_ids, day_templates):
        BaseTimetableModel.__init__(self)
        self.timetableDayIds = day_ids
        self.dayTemplates = day_templates
        self._validateDayTemplates()

    def _dayGenerator(self):
        return itertools.cycle(self.timetableDayIds)

    def schooldayStrategy(self, date, generator):
        if date in self.exceptionDayIds:
            return self.exceptionDayIds[date]
        else:
            return generator.next()


class WeeklyTimetableModel(BaseTimetableModel):
    """A timetable model where the schedule depends only on weekdays."""

    factory_id = "WeeklyTimetableModel"

    timetableDayIds = "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"

    classProvides(ITimetableModelFactory)

    def __init__(self, day_ids=None, day_templates={}):
        BaseTimetableModel.__init__(self)
        self.dayTemplates = day_templates
        if day_ids is not None:
            self.timetableDayIds = day_ids
        self._validateDayTemplates()

    def schooldayStrategy(self, date, generator):
        if date in self.exceptionDayIds:
            return self.exceptionDayIds[date]
        try:
            return self.timetableDayIds[date.weekday()]
        except IndexError:
            return None

    def _dayGenerator(self):
        return None


class TimetableCalendarEvent(CalendarEvent):

    implements(ITimetableCalendarEvent)

    period_id = property(lambda self: self._period_id)
    activity = property(lambda self: self._activity)

    def __init__(self, *args, **kwargs):
        self._period_id = kwargs.pop('period_id')
        self._activity = kwargs.pop('activity')
        CalendarEvent.__init__(self, *args, **kwargs)


