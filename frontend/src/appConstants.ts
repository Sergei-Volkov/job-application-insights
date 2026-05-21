export const DISCOVERY_SOURCES = [
  { key: 'wwr', label: 'We Work Remotely' },
  { key: 'working_nomads', label: 'Working Nomads' },
  { key: 'remoteok', label: 'Remote OK' },
  { key: 'remotive', label: 'Remotive' },
  { key: 'arbeitnow', label: 'Arbeitnow' },
  { key: 'jobicy', label: 'Jobicy' },
] as const

export const NEXT_STEP_CHIP_LABELS: Record<string, string> = {
  'Review role requirements': 'Review',
  'Tailor CV': 'Tailor CV',
  'Write cover letter': 'Cover Letter',
  'Submit application': 'Submit',
  'Prepare for interview': 'Interview Prep',
  'Follow up with recruiter': 'Follow-up',
  'Wait for response': 'Waiting',
}

export const NEXT_STEP_OPTIONS = [
  'Review role requirements',
  'Tailor CV',
  'Write cover letter',
  'Submit application',
  'Prepare for interview',
  'Follow up with recruiter',
  'Wait for response',
]
