import pandas as pd

df = pd.read_excel(r'C:\Users\adamc\PycharmProjects\winddataAPI\excelfile\specialist_blinds_FINAL_v2.xlsx')
with open(r'C:\Users\adamc\PycharmProjects\winddataAPI\scripts\excel_output.txt', 'w', encoding='utf-8') as f:
    f.write("Shape: " + str(df.shape) + "\n")
    f.write("Columns: " + str(list(df.columns)) + "\n\n")
    f.write("First 20 rows:\n")
    f.write(df.head(20)[['Keyword','URL','Ranking','Cannibalisation Severity','Action']].to_string() + "\n\n")
    f.write("Blank actions: " + str(df['Action'].isna().sum()) + "\n")

