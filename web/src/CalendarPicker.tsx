import { useMemo, useState } from 'react';
import { Calendar as CalendarIcon } from 'lucide-react';

import { Calendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

interface CalendarPickerProps {
  availableDates: string[];
  selectedDate: string;
  onSelectDate: (date: string) => void;
}

const RECENT_COUNT = 7;

function parseDate(dateString: string): Date {
  const [year, month, day] = dateString.split('-').map(Number);
  return new Date(year, month - 1, day);
}

function formatDate(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export default function CalendarPicker({
  availableDates,
  selectedDate,
  onSelectDate,
}: CalendarPickerProps) {
  const availableSet = useMemo(() => new Set(availableDates), [availableDates]);
  const recentDates = useMemo(() => availableDates.slice(0, RECENT_COUNT), [availableDates]);
  const [isOpen, setIsOpen] = useState(false);

  const selectedDateObj = parseDate(selectedDate);

  return (
    <div className="w-full sm:w-auto">
      <div className="flex items-center gap-2 w-full sm:w-auto flex-wrap">
        <span className="text-sm text-slate-400 whitespace-nowrap">选择日期:</span>

        <div className="flex gap-1.5 flex-wrap items-center">
          {recentDates.map(availableDate => (
            <button
              key={availableDate}
              onClick={() => onSelectDate(availableDate)}
              className={cn(
                'px-3 py-1.5 rounded-md text-sm font-semibold transition-all',
                availableDate === selectedDate
                  ? 'bg-gradient-to-r from-emerald-500 to-teal-500 text-white shadow-lg shadow-emerald-500/30'
                  : 'bg-slate-700/50 text-slate-300 hover:bg-slate-600/50 border border-slate-600/50',
              )}
            >
              {availableDate}
            </button>
          ))}

          {availableDates.length > 0 && (
            <Popover open={isOpen} onOpenChange={setIsOpen}>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  className={cn(
                    'px-3 py-1.5 h-auto rounded-md text-sm font-semibold bg-slate-800/60 text-slate-200 border-slate-600/60 hover:bg-slate-700/60 transition',
                    isOpen && 'bg-slate-700/60',
                  )}
                >
                  <CalendarIcon className="h-4 w-4" />
                  日历
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-auto p-0" align="start">
                <Calendar
                  mode="single"
                  selected={selectedDateObj}
                  onSelect={date => {
                    if (!date) return;
                    const dateKey = formatDate(date);
                    if (!availableSet.has(dateKey)) return;
                    onSelectDate(dateKey);
                    setIsOpen(false);
                  }}
                  disabled={date => !availableSet.has(formatDate(date))}
                  initialFocus
                />
              </PopoverContent>
            </Popover>
          )}
        </div>
      </div>
    </div>
  );
}