class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/b6/bd/062703267a3d9d24ad44c93dee8d6f5864a228290ab07bfd559fa819f10e/agentops_mcp_server-0.1.4.tar.gz"
  sha256 "d3902615d82c693f960d4b10f92df11a8bc77cbaae59ea14cd78409f673ff309"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
