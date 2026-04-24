import BrandingSection from './sections/BrandingSection'
import PromptsSection from './sections/PromptsSection'
import RAGSection from './sections/RAGSection'
import RAGPipelineSection from './sections/RAGPipelineSection'
import TablesSection from './sections/TablesSection'
import GlossarySection from './sections/GlossarySection'
import OrgsSection from './sections/OrgsSection'
import LLMSection from './sections/LLMSection'
import SMTPSection from './sections/SMTPSection'
import GuardrailsSection from './sections/GuardrailsSection'

export default function GeneralTab() {
  return (
    <div className="max-w-4xl space-y-6">
      <BrandingSection />
      <PromptsSection />
      <RAGSection />
      <RAGPipelineSection />
      <TablesSection />
      <GlossarySection />
      <OrgsSection />
      <LLMSection />
      <SMTPSection />
      <GuardrailsSection />
    </div>
  )
}
