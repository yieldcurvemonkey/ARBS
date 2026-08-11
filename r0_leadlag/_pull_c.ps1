Set-Location 'C:\Users\chris\clee\ARBS-r0\r0_leadlag'
& 'C:\Users\chris\anaconda3\envs\stir\python.exe' scratch_d1_fullwin.py 3y 2>&1 | Out-File -Append -Encoding utf8 'C:\Users\chris\clee\ARBS-r0\r0_leadlag\out\_pull_c.log'
& 'C:\Users\chris\anaconda3\envs\stir\python.exe' scratch_d1_fullwin.py 7y 2>&1 | Out-File -Append -Encoding utf8 'C:\Users\chris\clee\ARBS-r0\r0_leadlag\out\_pull_c.log'
'GROUP_c_DONE' | Out-File -Append -Encoding utf8 'C:\Users\chris\clee\ARBS-r0\r0_leadlag\out\_pull_c.log'
