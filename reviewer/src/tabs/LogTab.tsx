import type { State } from "@contract/state";
import { LogTable } from "@/components/LogTable";
import { Section, TabPage } from "@/components/Section";

export function LogTab({ state }: { state: State }) {
  const count = (lvl: string) => state.log.filter((e) => e.level === lvl).length;
  const warn = count("warn");
  const error = count("error");
  return (
    <TabPage>
      <Section
        title="Entries, newest first"
        aside={
          <span className="num">
            {state.log.length} total · <span className={warn ? "text-warn" : undefined}>{warn} warn</span> ·{" "}
            <span className={error ? "text-signal" : undefined}>{error} error</span>
          </span>
        }
      >
        <LogTable log={state.log} />
      </Section>
    </TabPage>
  );
}
