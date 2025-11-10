export type CsvRecord = Record<string, string>;

function normaliseNewlines(value: string): string {
  return value.replace(/\r\n?/g, '\n');
}

function parseCsvRows(text: string): string[][] {
  const rows: string[][] = [];
  let currentField = '';
  let currentRow: string[] = [];
  let inQuotes = false;

  const input = normaliseNewlines(text).replace(/^\ufeff/, '');

  for (let index = 0; index < input.length; index += 1) {
    const char = input[index];

    if (inQuotes) {
      if (char === '"') {
        const nextChar = input[index + 1];
        if (nextChar === '"') {
          currentField += '"';
          index += 1;
        } else {
          inQuotes = false;
        }
      } else {
        currentField += char;
      }
      continue;
    }

    if (char === '"') {
      inQuotes = true;
      continue;
    }

    if (char === ',') {
      currentRow.push(currentField);
      currentField = '';
      continue;
    }

    if (char === '\n') {
      currentRow.push(currentField);
      rows.push(currentRow);
      currentRow = [];
      currentField = '';
      continue;
    }

    currentField += char;
  }

  currentRow.push(currentField);
  rows.push(currentRow);

  // Remove trailing empty rows
  while (rows.length && rows[rows.length - 1].every((field) => field === '')) {
    rows.pop();
  }

  return rows;
}

export function parseCsv(text: string): CsvRecord[] {
  const rows = parseCsvRows(text);
  if (!rows.length) {
    return [];
  }

  const [header, ...dataRows] = rows;
  const headers = header.map((value) => value.trim());

  return dataRows
    .map((row) => {
      const record: CsvRecord = {};
      headers.forEach((key, index) => {
        if (!key) {
          return;
        }
        record[key] = row[index] ?? '';
      });
      return record;
    })
    .filter((record) => Object.values(record).some((value) => value.trim().length > 0));
}

export function parseCsvForTesting(text: string): string[][] {
  return parseCsvRows(text);
}
