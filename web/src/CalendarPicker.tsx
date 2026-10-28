import { useMemo, useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { Calendar } from "@/components/ui/calendar";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

interface CalendarPickerProps {
  availableDates: string[];
  selectedDate: string;
  onSelectDate: (date: string) => void;
  label?: string;
  disabled?: boolean;
}

function parseDate(value: string): Date {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day);
}
function dateKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

export default function CalendarPicker({
  availableDates,
  selectedDate,
  onSelectDate,
  label = "扫描交易日",
  disabled = false,
}: CalendarPickerProps) {
  const dates = useMemo(
    () => [...new Set(availableDates)].sort().reverse(),
    [availableDates],
  );
  const available = useMemo(() => new Set(dates), [dates]);
  const [open, setOpen] = useState(false);
  const [month, setMonth] = useState<Date>();
  const selected = available.has(selectedDate)
    ? parseDate(selectedDate)
    : undefined;
  const index = dates.indexOf(selectedDate);
  const unavailable = disabled || dates.length === 0;
  const move = (offset: number) => {
    const next = dates[index + offset];
    if (next) onSelectDate(next);
  };
  return (
    <div className="space-y-3" aria-label={label}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-1 text-sm text-slate-500">{label}</span>
        <Popover
          open={open}
          onOpenChange={(next) => {
            if (next)
              setMonth(
                selected ?? (dates[0] ? parseDate(dates[0]) : undefined),
              );
            setOpen(next);
          }}
        >
          <PopoverTrigger asChild>
            <button
              type="button"
              disabled={unavailable}
              aria-label={`选择${label}`}
              className="tg-input inline-flex min-w-[174px] items-center justify-between gap-3 disabled:opacity-50"
            >
              <span>{selectedDate || "暂无可用日期"}</span>
              <CalendarDays className="h-4 w-4 text-slate-500" />
            </button>
          </PopoverTrigger>
          <PopoverContent
            align="start"
            className="w-auto max-w-[calc(100vw-24px)] rounded-xl border-slate-200 bg-white p-1 text-slate-900 shadow-xl"
          >
            <Calendar
              mode="single"
              selected={selected}
              month={month}
              onMonthChange={setMonth}
              captionLayout="dropdown-buttons"
              fromDate={
                dates.length ? parseDate(dates[dates.length - 1]) : undefined
              }
              toDate={dates.length ? parseDate(dates[0]) : undefined}
              weekStartsOn={1}
              showOutsideDays={false}
              formatters={{
                formatMonthCaption: (date) => `${date.getMonth() + 1} 月`,
                formatWeekdayName: (date) =>
                  ["日", "一", "二", "三", "四", "五", "六"][date.getDay()],
              }}
              labels={{
                labelMonthDropdown: () => "选择月份",
                labelYearDropdown: () => "选择年份",
                labelPrevious: () => "上个月",
                labelNext: () => "下个月",
                labelDay: (date) => dateKey(date),
              }}
              classNames={{
                caption_dropdowns: "flex items-center gap-1 px-8",
                dropdown:
                  "rounded-md border border-slate-300 bg-slate-100 px-1 py-1 text-sm text-slate-900",
                vhidden: "sr-only",
                dropdown_icon: "hidden",
                caption_label: "hidden",
                day_selected:
                  "bg-emerald-500 text-slate-950 hover:bg-emerald-400 focus:bg-emerald-400",
                day_disabled: "text-slate-600 opacity-40 cursor-not-allowed",
              }}
              disabled={(date) => !available.has(dateKey(date))}
              onSelect={(date) => {
                if (date && available.has(dateKey(date))) {
                  onSelectDate(dateKey(date));
                  setOpen(false);
                }
              }}
              footer={
                <p className="pt-3 text-center text-xs text-slate-500">
                  仅可选择当前来源有股票缓存的交易日
                </p>
              }
              initialFocus
            />
          </PopoverContent>
        </Popover>
        <div className="flex gap-1">
          <button
            type="button"
            aria-label="前一个可用交易日"
            disabled={unavailable || index < 0 || index >= dates.length - 1}
            onClick={() => move(1)}
            className="tg-button p-2 disabled:cursor-not-allowed"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button
            type="button"
            aria-label="后一个可用交易日"
            disabled={unavailable || index <= 0}
            onClick={() => move(-1)}
            className="tg-button p-2 disabled:cursor-not-allowed"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
        <button
          type="button"
          disabled={unavailable || selectedDate === dates[0]}
          onClick={() => onSelectDate(dates[0])}
          className="text-xs text-emerald-700 disabled:text-slate-600"
        >
          最新缓存日
        </button>
      </div>
      {dates.length > 0 && (
        <div
          className="flex flex-wrap items-center gap-1.5"
          aria-label="最近可用交易日"
        >
          <span className="mr-1 text-xs text-slate-500">最近</span>
          {dates.slice(0, 5).map((day) => (
            <button
              type="button"
              key={day}
              disabled={disabled}
              aria-pressed={day === selectedDate}
              onClick={() => onSelectDate(day)}
              className={`rounded-md border px-2.5 py-1 text-xs transition ${day === selectedDate ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700" : "border-slate-200 text-slate-500 hover:border-slate-500 hover:text-slate-700"}`}
            >
              {day}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
