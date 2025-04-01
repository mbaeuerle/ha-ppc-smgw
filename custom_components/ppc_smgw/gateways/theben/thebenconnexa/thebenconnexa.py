import httpx

from custom_components.ppc_smgw.gateways.reading import Information, OBISCode, Reading
from datetime import datetime


class ThebenConnexaClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        httpx_client: httpx.AsyncClient,
        logger,
    ):
        self.base_url = base_url
        self.username = username
        self.password = password

        self.httpx_client = httpx_client
        self.logger = logger

        self.httpx_client.headers.setdefault("Content-Type", "application/json")
        self.httpx_client.follow_redirects = True

    def _get_auth(self) -> httpx.DigestAuth:
        auth = httpx.DigestAuth(self.username, self.password)
        self.httpx_client.auth = auth

        return auth

    async def get_data(self) -> Information:
        information = Information(
            firmware_version=await self._get_firmware_version(),
            readings=await self._get_readings(),
            last_update=datetime.now(),
        )

        self.logger.debug(f"Returning information: {information}")

        return information

    async def _get_readings(self) -> dict[OBISCode, Reading]:
        user_info = await self._get_user_info()

        try:
            response = await self.httpx_client.post(
                self.base_url,
                auth=self._get_auth(),
                timeout=10,
                json={
                    "method": "readings",
                    "database": "origin",
                    "usage-point-id": user_info,
                    "last-reading": "true",
                }
            )
        except Exception as e:
            self.logger.error(f"Failed to fetch readings: {e}")
            return {}

        channels = response.json()['readings']['channels']

        readings = {}
        for channel in channels:
            obis = channel['obis']
            self.logger.debug(f"Got channel: {channel}")
            for reading in channel['readings']:
                self.logger.debug(f"Got reading: {reading}")
                readings[obis] = Reading(
                    # The value is missing the decimal point but has 4 digits after the decimal point
                    value=str(float(reading['value']) / 10000),
                    unit="kWh",
                    timestamp=datetime.fromisoformat(reading['capture-time']),
                    isvalid="1", # TODO: Not sure what this means
                    name=obis, # TODO: Not sure what name to use here
                    obis=obis,
                )
        return readings

    async def _get_user_info(self) -> str:
        try:
            response = await self.httpx_client.post(
                self.base_url,
                auth=self._get_auth(),
                timeout=10,
                json={"method": "user-info"}
            )
        except Exception as e:
            self.logger.error(f"Failed to fetch user-info: {e}")
            return "Unknown"

        usage_points = response.json()['user-info']['usage-points']
        # There can be multiple usage points, so we need to get the correct one to get the latest readings.
        # We sort the usage points by taf-number because sometimes there is more than one in running state.
        # Making the assumption the one with the lower taf-number is the one we want we can just take the first one later on.
        # Then we filter out the ones that are not in running state
        self.logger.debug(f"Got usage-points: {usage_points}")
        usage_points.sort(key=lambda x: x['taf-state'])
        filtered_points = [
            point['usage-point-id'] for point in usage_points
            if point.get('taf-state') == 'running'
        ]
        if not filtered_points:
            self.logger.warning("No usage points found in running state")
            return "Unknown"
        self.logger.debug(f"Choosing usage point: {filtered_points[0]}")
        return filtered_points[0]

    async def _get_firmware_version(self) -> str:
        self.logger.debug(f"Getting firmware version from {self.base_url}")

        try:
            response = await self.httpx_client.post(
                self.base_url,
                auth=self._get_auth(),
                timeout=10,
                json={"method": "smgw-info"},
            )
        except Exception as e:
            self.logger.error(f"Failed to fetch firmware version: {e}")
            return "Unknown"

        smgw_info = response.json()

        self.logger.debug(
            f"Got firmware info response: \nStatus code: {response.status_code}\nRaw response: {response.text}"
        )

        try:
            return f"{smgw_info['smgw-info']['firmware-info']['version']}-{smgw_info['smgw-info']['firmware-info']['hash']}"
        except KeyError as e:
            self.logger.error(
                f"Failed to get firmware info: {e}.\nReponse from SMGW: {response.json()}"
            )

        return "Unknown"
