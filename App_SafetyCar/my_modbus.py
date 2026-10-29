from pymodbus.client import ModbusTcpClient
from pymodbus.exceptions import ModbusException
from pymodbus.pdu import ExceptionResponse
from typing import Any, Generic, TypeVar, List,Union


def get_int(data_: list, word_index: int) ->int:
    if data_ and len(data_)>0:
        return data_[word_index]
    return 0

def get_bool(data_: list, word_index: int, bool_index: int) -> bool:
        """Get the boolean value from location in bytearray

        Args:
            bytearray_: buffer data.
            byte_index: byte index to read from.
            bool_index: bit index to read from.

        Returns:
            True if the bit is 1, else 0.

        Examples:
            >>> buffer = bytearray([0b00000001])  # Only one byte length
            >>> get_bool(buffer, 0, 0)  # The bit 0 starts at the right.
                True
        """
        if data_ and len(data_)>0:

            index_value = 1 << bool_index
            word_value = data_[word_index]
            current_value = word_value & index_value
            return current_value == index_value
        
def set_bool(data_: list, word_index: int, bool_index: int, value: bool):
    """Set boolean value on location in bytearray.

    Args:
        bytearray_: buffer to write to.
        word_index: byte index to write to.
        bool_index: bit index to write to.
        value: value to write.

    Examples:
        >>> buffer = bytearray([0b00000000])
        >>> set_bool(buffer, 0, 0, True)
        >>> buffer
            bytearray(b"\\x01")
    """
    if value not in {0, 1, True, False}:
        raise TypeError(f"Value value:{value} is not a boolean expression.")

    current_value = get_bool(data_, word_index, bool_index)
    index_value = 1 << bool_index

    # check if bool already has correct value
    if current_value == value:
        return

    if value:
        # make sure index_v is IN current byte
        data_[word_index] += index_value
    else:
        # make sure index_v is NOT in current byte
        data_[word_index] -= index_value

class ModbusClient:
    def __init__(self):
        self.client = None
        self.connected = False
        
    def connect(self, ip, port=502, timeout=1.0):
        """连接到Modbus TCP服务器"""
        try:
            self.client = ModbusTcpClient(
                host=ip,
                port=port,
                timeout=timeout
            )
            self.connected = self.client.connect()
            return self.connected
        except Exception as e:
            print(f"连接失败: {e}")
            return False
            
    def disconnect(self):
        """断开连接"""
        if self.client:
            self.client.close()
        self.connected = False
        
    def read_coils(self, address, count=1, unit=1):
        """读取线圈状态(0x01功能码)"""
        if not self.connected:
            raise RuntimeError("未连接到Modbus设备")
            
        try:
            response = self.client.read_coils(address, count=count, device_id=unit)
            if isinstance(response, ExceptionResponse):
                raise ModbusException(response)
            return [bit for bit in response.bits[:count]]
        except ModbusException as e:
            print(f"读取线圈失败: {e}")
            return None
            
    def read_discrete_inputs(self, address, count=1, unit=1):
        """读取离散输入(0x02功能码)"""
        if not self.connected:
            raise RuntimeError("未连接到Modbus设备")
            
        try:
            response = self.client.read_discrete_inputs(address, count=count, device_id=unit)
            if isinstance(response, ExceptionResponse):
                raise ModbusException(response)
            return [bit for bit in response.bits[:count]]
        except ModbusException as e:
            print(f"读取离散输入失败: {e}")
            return None
            
    def read_holding_registers(self, address, count=1, unit=1):
        """读取保持寄存器(0x03功能码)"""
        if not self.connected:
            raise RuntimeError("未连接到Modbus设备")
            
        try:
            response = self.client.read_holding_registers(address, count=count, device_id=unit)
            if isinstance(response, ExceptionResponse):
                raise ModbusException(response)
            return response.registers[:count]
        except ModbusException as e:
            print(f"读取保持寄存器失败: {e}")
            return None
            
    def read_input_registers(self, address, count=1, unit=1):
        """读取输入寄存器(0x04功能码)"""
        if not self.connected:
            raise RuntimeError("未连接到Modbus设备")
            
        try:
            response = self.client.read_input_registers(address, count=count, device_id=unit)
            if isinstance(response, ExceptionResponse):
                raise ModbusException(response)
            return response.registers[:count]
        except ModbusException as e:
            print(f"读取输入寄存器失败: {e}")
            return None
            
    def write_coil(self, address, value, unit=1):
        """写入单个线圈(0x05功能码)"""
        if not self.connected:
            raise RuntimeError("未连接到Modbus设备")
            
        try:
            response = self.client.write_coil(address, value, device_id=unit)
            if isinstance(response, ExceptionResponse):
                raise ModbusException(response)
            return True
        except ModbusException as e:
            print(f"写入线圈失败: {e}")
            return False
            
    def write_registers(self, address, values: Union[List[int], int], unit=1):
        """写入单个寄存器(0x06功能码)"""
        if not self.connected:
            raise RuntimeError("未连接到Modbus设备")
            
        try:
            if isinstance(values,int):
                response = self.client.write_registers(address, [values], device_id=unit)
            else:
                response = self.client.write_registers(address, values, device_id=unit)
            if isinstance(response, ExceptionResponse):
                raise ModbusException(response)
            return True
        except ModbusException as e:
            print(f"写入寄存器失败: {e}")
            return False
            
    def write_coils(self, address, values, unit=1):
        """写入多个线圈(0x0F功能码)"""
        if not self.connected:
            raise RuntimeError("未连接到Modbus设备")
            
        try:
            response = self.client.write_coils(address, values, device_id=unit)
            if isinstance(response, ExceptionResponse):
                raise ModbusException(response)
            return True
        except ModbusException as e:
            print(f"写入多个线圈失败: {e}")
            return False
            
    # def write_registers(self, address, values, unit=1):
    #     """写入多个寄存器(0x10功能码)"""
    #     if not self.connected:
    #         raise RuntimeError("未连接到Modbus设备")
            
    #     try:
    #         response = self.client.write_registers(address, values, device_id=unit)
    #         if isinstance(response, ExceptionResponse):
    #             raise ModbusException(response)
    #         return True
    #     except ModbusException as e:
    #         print(f"写入多个寄存器失败: {e}")
    #         return False
