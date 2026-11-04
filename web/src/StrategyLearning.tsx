import { Plugin } from "./backtestApi";

type Property = {
  title?: string;
  description?: string;
  type?: string;
  enum?: string[];
  default?: unknown;
  anyOf?: Property[];
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
};
const input =
  "w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900";

function properties(plugin: Plugin): Record<string, Property> {
  return (plugin.parameters_schema?.properties || {}) as Record<
    string,
    Property
  >;
}
const display = (value: unknown) =>
  value == null
    ? "留空 / 关闭"
    : typeof value === "boolean"
      ? value
        ? "是"
        : "否"
      : String(value);

export function StrategyLearning({
  plugin,
  open = false,
  parameters,
}: {
  plugin: Plugin;
  open?: boolean;
  parameters?: Record<string, unknown>;
}) {
  const guide = plugin.education;
  if (!guide)
    return (
      <p className="mt-3 text-xs text-slate-500">该版本未归档学习说明。</p>
    );
  const section = (title: string, rows: string[]) => (
    <section className="space-y-1">
      <h4 className="font-semibold text-slate-800">{title}</h4>
      <ul className="list-disc space-y-1 pl-4">
        {rows.map((row) => (
          <li key={row}>{row}</li>
        ))}
      </ul>
    </section>
  );
  return (
    <details
      open={open || undefined}
      className="mt-3 text-xs leading-6 text-slate-600"
      aria-label={`${plugin.title}学习说明`}
    >
      <summary className="cursor-pointer font-medium text-blue-700">
        学习思路与条件
      </summary>
      <div className="mt-3 space-y-4">
        <section>
          <h4 className="font-semibold text-slate-800">为什么这样做</h4>
          <p>{guide.idea}</p>
        </section>
        {section("入场 / 调仓条件", guide.entry)}
        {section("退出条件", guide.exit)}
        {guide.suitable_for && section("适用研究场景", guide.suitable_for)}
        <section>
          <h4 className="font-semibold text-slate-800">仓位如何确定</h4>
          <p>{guide.sizing}</p>
        </section>
        {(Object.keys(properties(plugin)).length > 0 ||
          guide.fixed_parameters.length > 0) && (
          <section>
            <h4 className="font-semibold text-slate-800">
              参数释义 · {parameters ? "本次配置" : "默认值是研究示例"}
            </h4>
            {guide.fixed_parameters.length > 0 && (
              <ul className="list-disc pl-4">
                {guide.fixed_parameters.map((text) => (
                  <li key={text}>{text}（此插件固定条件）</li>
                ))}
              </ul>
            )}
            <dl className="space-y-2">
              {Object.entries(properties(plugin)).map(([name, spec]) => (
                <div key={name}>
                  <dt className="font-medium text-slate-700">
                    {spec.title || name}：
                    {display(
                      parameters &&
                        Object.prototype.hasOwnProperty.call(parameters, name)
                        ? parameters[name]
                        : (plugin.default_parameters?.[name] ?? spec.default),
                    )}
                  </dt>
                  <dd>{spec.description || "参数意义由插件定义。"}</dd>
                </div>
              ))}
            </dl>
          </section>
        )}
        {section(`数据与预热 · 默认至少 ${plugin.min_history} 根`, guide.data)}
        <section className="rounded-lg bg-blue-50 p-3">
          <h4 className="font-semibold text-blue-900">
            用数字理解（合成例子）
          </h4>
          <p>{guide.example}</p>
        </section>
        {section("什么时候容易失效 / 需要注意", guide.pitfalls)}
        <section>
          <h4 className="font-semibold text-slate-800">版本与原始方法的差异</h4>
          <p>{guide.variant}</p>
          {plugin.kind === "signal" && (
            <p className="mt-1">
              这是候选信号。组合门槛、排序和资金仍由交易策略决定；退出需显式勾选信号退出或填写其他退出条件。
            </p>
          )}
        </section>
        <section>
          <h4 className="font-semibold text-slate-800">继续阅读 / 规则来源</h4>
          <ul>
            {guide.sources.map((source) => (
              <li key={source.title}>
                {source.url?.startsWith("https://") ? (
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-blue-700 underline"
                  >
                    {source.title}
                  </a>
                ) : (
                  source.title
                )}
              </li>
            ))}
          </ul>
        </section>
      </div>
    </details>
  );
}

export function StrategyParameters({
  plugin,
  value,
  onChange,
}: {
  plugin: Plugin;
  value: string;
  onChange: (value: string) => void;
}) {
  let parsed: Record<string, unknown> = {};
  let invalid = false;
  try {
    const result = JSON.parse(value);
    if (!result || typeof result !== "object" || Array.isArray(result))
      invalid = true;
    else parsed = result;
  } catch {
    invalid = true;
  }
  const fields = properties(plugin);
  const update = (name: string, next: unknown) =>
    onChange(
      JSON.stringify({ ...plugin.default_parameters, ...parsed, [name]: next }),
    );
  if (!Object.keys(fields).length)
    return (
      <p className="text-xs text-slate-500">
        此插件使用固定条件，详见学习说明。仓位和退出配置仍可在实验中设置。
      </p>
    );
  return (
    <fieldset aria-label={`${plugin.title}参数`} className="space-y-3">
      <legend className="mb-2 text-xs font-medium text-slate-700">
        策略参数（研究默认值，可编辑）
      </legend>
      {!invalid && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {Object.entries(fields).map(([name, spec]) => {
            const options = spec.anyOf || [spec];
            const numeric = options.find(
              (option) => option.type === "integer" || option.type === "number",
            );
            const nullable = options.some((option) => option.type === "null");
            const current = Object.prototype.hasOwnProperty.call(parsed, name)
              ? parsed[name]
              : (plugin.default_parameters?.[name] ?? spec.default);
            return (
              <label
                key={name}
                className="block space-y-1 text-xs text-slate-600"
              >
                <span className="font-medium">{spec.title || name}</span>
                {spec.enum ? (
                  <select
                    className={input}
                    value={String(current ?? "")}
                    onChange={(e) => update(name, e.target.value)}
                  >
                    {spec.enum.map((item) => (
                      <option key={item} value={item}>
                        {item === "sma"
                          ? "简单均线 SMA"
                          : item === "ema"
                            ? "指数均线 EMA"
                            : item}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    className={input}
                    type={numeric ? "number" : "text"}
                    step={numeric?.type === "integer" ? "1" : "any"}
                    min={numeric?.minimum}
                    max={numeric?.maximum}
                    value={current == null ? "" : String(current)}
                    placeholder={nullable ? "留空关闭" : undefined}
                    onChange={(e) =>
                      update(
                        name,
                        e.target.value === "" && nullable
                          ? null
                          : numeric?.type === "integer"
                            ? e.target.value === ""
                              ? ""
                              : Number(e.target.value)
                            : e.target.value,
                      )
                    }
                  />
                )}
                <span className="block text-[11px] leading-5 text-slate-500">
                  {spec.description}
                </span>
              </label>
            );
          })}
        </div>
      )}
      {invalid && (
        <p role="alert" className="text-xs text-red-700">
          高级参数不是有效的 JSON 对象，请修正后再编辑表单。
        </p>
      )}
      <details open={invalid || undefined} className="text-xs text-slate-500">
        <summary className="cursor-pointer">高级：查看或编辑参数 JSON</summary>
        <textarea
          aria-label={`${plugin.title}高级参数 JSON`}
          className={input + " mt-2 font-mono"}
          rows={4}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      </details>
    </fieldset>
  );
}
