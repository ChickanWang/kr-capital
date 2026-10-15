import { colorSchemeDark, themeQuartz } from 'ag-grid-community'

/** The dark AG Grid theme shared by the universe grid and the holdings screener. */
export const gridTheme = themeQuartz.withPart(colorSchemeDark).withParams({
  backgroundColor: '#11161d',
  headerBackgroundColor: '#161c25',
  fontSize: 13,
  spacing: 6,
})
