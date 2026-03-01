from typing import Mapping, Literal
import httpx 

HTTPXProxies = Mapping[Literal['http://', 'https://'], httpx.AsyncHTTPTransport]