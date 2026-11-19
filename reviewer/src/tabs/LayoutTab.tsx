import type { State } from "@contract/state";
import { ScreenshotGallery } from "@/components/Screenshots";
import { Section, TabPage } from "@/components/Section";

export function LayoutTab({ state }: { state: State }) {
  const n = state.screenshots.length;
  return (
    <TabPage aside={<span>KLayout captures — the layout itself is not rendered in the browser</span>}>
      <Section title="Screenshots" aside={`${n} image${n === 1 ? "" : "s"}`}>
        <ScreenshotGallery shots={state.screenshots} steps={state.steps} />
      </Section>
    </TabPage>
  );
}
