Set-Location 'C:\Users\chris\clee\ARBS-r0\r0_leadlag'
& 'C:\Users\chris\anaconda3\envs\stir\python.exe' scratch_d1_fullwin.py 30y 2>&1 | Out-File -Append -Encoding utf8 'C:\Users\chris\clee\ARBS-r0\r0_leadlag\out\_pull_a.log'
& 'C:\Users\chris\anaconda3\envs\stir\python.exe' scratch_d1_fullwin.py 20y 2>&1 | Out-File -Append -Encoding utf8 'C:\Users\chris\clee\ARBS-r0\r0_leadlag\out\_pull_a.log'
'GROUP_a_DONE' | Out-File -Append -Encoding utf8 'C:\Users\chris\clee\ARBS-r0\r0_leadlag\out\_pull_a.log'
